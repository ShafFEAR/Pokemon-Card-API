"""Scrapes PSA CardFacts pages for the most recent sale price per grade.

Unlike the Price Guide (grades 7-10, PSA's own valuation) and Auction Prices
Realized (behind a Collectors.com login), CardFacts card pages are public and
show, per grade 1-10 + Authentic: the most recent sale price, the average
sale price, PSA's price, and population - plus the individual sales those
come from. robots.txt allows /cardfacts with "Crawl-delay: 1".

The catch is coverage: CardFacts only exists for a curated subset of cards -
78 Pokemon sets (none newer than 2020), and within those, only checklist
entries PSA wrote a CardFacts page for (~1,400 of ~11,500). Checklist entries
without a page have no public "most recent price" anywhere on psacard.com.

Discovery is three steps, all JSON/HTML endpoints the CardFacts site itself
uses:
  1. GET  /CardFacts/GetSets/7/...   every Non-Sports set (category 7)
  2. POST /cardfacts/GetSetList      one set's checklist; entries with a page
                                     are an <a href=".../{slug}/{cardfactsId}">
  3. GET  /cardfacts/non-sports-cards/{setSlug}/{slug}/{cardfactsId}

Sets and cards go into the same psa_sets / psa_variants tables the Price
Guide pipeline uses (keyed by CardFacts ids instead), so psa.matcher can link
them to mirror cards unchanged. Per-grade prices are kept in memory and
returned, since they don't fit the psa_prices table's shape.
"""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import config, db
from .psa_client import PsaClient
from .psa_scraper import split_description

SETS_URL = f"{config.PSA_BASE_URL}/CardFacts/GetSets/7/non%20sports%20cards"
SET_LIST_URL = f"{config.PSA_BASE_URL}/cardfacts/GetSetList"
CARD_LINK_RE = re.compile(r"href='/cardfacts/[^']*?/([a-z0-9-]+)/(\d+)'")
TAG_RE = re.compile(r"<[^>]+>")

# CardFacts names Pokemon sets "1999 Nintendo Pokemon Game" / "1997 Tomy Pokemon
# Scratch Cards". The publisher word isn't part of any set name the mirror
# uses, so it's dropped from the stored slug to keep psa.matcher's name
# scores comparable to the Price Guide's "1999-poke-mon-game" style slugs.
PUBLISHER_RE = re.compile(r"^(\d{4}-)(nintendo|tomy|wizards)-")


def _num(text):
    """'1026.00' -> 1026.0; PSA uses '0' (shown as a dash) for no data."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value or None


def _grade_key(order):
    """'10' -> '10', '1.5' -> '1.5', '0' -> 'Auth' (the Authentic row)."""
    value = float(order)
    if value == 0:
        return "Auth"
    return str(int(value)) if value.is_integer() else str(value)


def _iso_date(order):
    """'20250926' -> '2025-09-26'."""
    return f"{order[:4]}-{order[4:6]}-{order[6:8]}" if order and len(order) == 8 else None


def _cells(tr):
    return {td.get("data-title"): td for td in tr.find_all("td")}


def parse_card_page(html):
    """Returns {grade: {mostRecent, mostRecentDate, average, psaPrice, population}}
    for every grade with at least one non-empty value."""
    soup = BeautifulSoup(html, "html.parser")
    summary = soup.find("table", id="tablePricesSummary")
    if summary is None or summary.find("tbody") is None:
        return {}

    # Newest sale per (grade, price), to date each grade's "Most Recent Price".
    # The sales table is newest-first, so the first hit wins.
    sale_dates = {}
    sales = soup.find("table", id="tableAuctionPrices")
    if sales is not None and sales.find("tbody") is not None:
        for tr in sales.find("tbody").find_all("tr"):
            c = _cells(tr)
            if "Grade" not in c or "Price" not in c or "Date" not in c:
                continue
            key = (_grade_key(c["Grade"].get("data-order") or "0"), _num(c["Price"].get("data-order")))
            sale_dates.setdefault(key, _iso_date(c["Date"].get("data-order")))

    grades = {}
    for tr in summary.find("tbody").find_all("tr"):
        c = _cells(tr)
        if "Grade" not in c:
            continue
        grade = _grade_key(c["Grade"].get("data-order") or "0")
        def order(title):
            return c[title].get("data-order") if title in c else None

        entry = {
            "mostRecent": _num(order("Most Recent Price")),
            "average": _num(order("Average Price")),
            "psaPrice": _num(order("PSA Price")),
            "population": int(_num(order("Population")) or 0),
        }
        if entry["mostRecent"] is not None:
            entry["mostRecentDate"] = sale_dates.get((grade, entry["mostRecent"]))
        if entry["mostRecent"] is None and entry["average"] is None and entry["psaPrice"] is None:
            continue
        grades[grade] = entry
    return grades


def sync_pokemon_sets(client):
    sets = client.get(SETS_URL).json()["Results"]
    pokemon = [s for s in sets if "pokemon" in s["ResultName"].lower()]
    now = datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        for s in pokemon:
            slug = PUBLISHER_RE.sub(r"\1", s["ResultNameSEO"])
            year = int(slug[:4]) if slug[:4].isdigit() else None
            conn.execute(
                """
                INSERT INTO psa_sets (psa_set_id, slug, display_name, year, url, is_japanese, last_crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(psa_set_id) DO UPDATE SET
                    slug=excluded.slug, display_name=excluded.display_name, year=excluded.year,
                    url=excluded.url, is_japanese=excluded.is_japanese, last_crawled_at=excluded.last_crawled_at
                """,
                (
                    str(s["ResultID"]),
                    slug,
                    s["ResultName"],
                    year,
                    f"{config.PSA_BASE_URL}/cardfacts/non-sports-cards/{s['ResultNameSEO']}/{s['ResultID']}",
                    1 if "japanese" in slug else 0,
                    now,
                ),
            )
    print(f"CardFacts catalog: {len(pokemon)} Pokemon sets (of {len(sets)} Non-Sports sets).")
    return pokemon


def sync_set_checklists(client, pokemon_sets):
    """Stores every checklist entry that has a CardFacts page; returns
    (cards_with_pages, total_checklist_entries)."""
    with_pages = []
    total_entries = 0
    now = datetime.now(timezone.utc).isoformat()
    for s in pokemon_sets:
        resp = client.post(
            SET_LIST_URL,
            data={"draw": 1, "start": 0, "length": 5000, "setID": s["ResultID"]},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        rows = resp.json()["data"]
        total_entries += len(rows)
        with db.connection() as conn:
            for row in rows:
                m = CARD_LINK_RE.search(row["CardName"])
                if not m:
                    continue
                card_slug, cardfacts_id = m.groups()
                description = TAG_RE.sub("", row["CardName"]).strip()
                base_name, variant_tag = split_description(description)
                conn.execute(
                    """
                    INSERT INTO psa_variants (psa_spec_id, psa_set_id, description, card_number,
                                              base_name, variant_tag, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(psa_spec_id) DO UPDATE SET
                        description=excluded.description, card_number=excluded.card_number,
                        base_name=excluded.base_name, variant_tag=excluded.variant_tag,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (cardfacts_id, str(s["ResultID"]), description, (row.get("CardNumber") or "").strip() or None,
                     base_name, variant_tag, now),
                )
                with_pages.append(
                    {
                        "cardfactsId": cardfacts_id,
                        "url": f"{config.PSA_BASE_URL}/cardfacts/non-sports-cards/"
                        f"{s['ResultNameSEO']}/{card_slug}/{cardfacts_id}",
                    }
                )
    print(f"CardFacts checklists: {len(with_pages)} of {total_entries} entries have a card page.")
    return with_pages, total_entries


def scrape_card_prices(client, cards, limit=None):
    """Returns {cardfactsId: grades} for each card page; failures are skipped."""
    if limit:
        cards = cards[:limit]
    prices = {}
    failed = []
    for i, card in enumerate(cards, start=1):
        try:
            prices[card["cardfactsId"]] = parse_card_page(client.get(card["url"]).text)
        except Exception as exc:  # noqa: BLE001 - one bad page shouldn't kill the run
            print(f"  [WARN] failed {card['url']}: {exc}")
            failed.append(card["cardfactsId"])
        if i % 100 == 0 or i == len(cards):
            print(f"  ...{i}/{len(cards)} card pages scraped")
    if failed:
        print(f"  Failed card pages ({len(failed)}): {', '.join(failed)}")
    return prices
