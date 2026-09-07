"""Scrapes PSA's per-set price table for every known Pokemon set.

PSA does not show the same set of grade columns on every set page - e.g. the
1999 Base Set ("Game") shows NM 7 / NM-MT 8 / MT 9 / GEM-MT 10, while its
Unlimited-print sibling page only shows NM-MT 8 / MT 9 / GEM-MT 10 (no NM 7
column at all). The column count and grade set is read from each page's own
table header rather than assumed, so this adapts per set instead of silently
dropping rows that don't match a hardcoded layout.

Each run appends a fresh timestamped snapshot to `psa_prices` rather than
overwriting, so price history accumulates across repeated runs.
"""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import db
from .psa_client import PsaClient

PRICE_COLUMN_START = 3  # columns are: [icon, description, card number, ...grades]
GRADE_HEADER_RE = re.compile(r"(\d{1,2})\s*$")

VARIANT_KEYWORDS = [
    "1st Edition",
    "Shadowless",
    "Unlimited",
    "Reverse Holo",
    "Holo",
    "Staff",
    "Error",
]


def parse_price(text):
    """'8,200-' -> (8200.0, 'down'); '' or '-' -> (None, None)."""
    text = text.strip()
    if not text or text == "-":
        return None, None
    trend = None
    if text.endswith("+"):
        trend, text = "up", text[:-1]
    elif text.endswith("-"):
        trend, text = "down", text[:-1]
    text = text.replace(",", "").strip()
    if not text:
        return None, trend
    try:
        return float(text), trend
    except ValueError:
        return None, trend


def split_description(desc):
    """'Charizard - Holo-1st Edition' -> ('Charizard', 'Holo-1st Edition')."""
    desc = desc.strip()
    if " - " in desc:
        base, variant = desc.split(" - ", 1)
        return base.strip(), variant.strip()
    for kw in sorted(VARIANT_KEYWORDS, key=len, reverse=True):
        suffix = "-" + kw
        if desc.endswith(suffix):
            return desc[: -len(suffix)].strip(), kw
    return desc, None


def _parse_grade_headers(table):
    """Reads which grade columns this specific page has, in left-to-right order."""
    thead = table.find("thead")
    if thead is None:
        return []
    grades = []
    for th in thead.find_all("th"):
        m = GRADE_HEADER_RE.search(th.get_text(strip=True))
        if m:
            grades.append(int(m.group(1)))
    return grades


def scrape_set(client, psa_set):
    resp = client.get(psa_set["url"])
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", id="tableSetPrices")
    if table is None:
        return []

    grade_headers = _parse_grade_headers(table)
    if not grade_headers:
        return []
    min_cols = PRICE_COLUMN_START + len(grade_headers)

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < min_cols:
            continue

        shop_link = tr.find("a", class_="shop-link")
        if shop_link is None or not shop_link.get("data-id"):
            # e.g. the "Commons" bulk row, which isn't tied to one card
            continue
        spec_id = shop_link["data-id"]

        desc_text = tds[1].get_text(" ", strip=True)
        desc_text = re.sub(r"\s*Shop with Affiliates\s*$", "", desc_text).strip()
        card_number = tds[2].get_text(strip=True) or None

        price_tds = tds[PRICE_COLUMN_START : PRICE_COLUMN_START + len(grade_headers)]
        grades = {}
        for grade, td in zip(grade_headers, price_tds):
            grades[grade] = parse_price(td.get_text(strip=True))

        base_name, variant_tag = split_description(desc_text)
        rows.append(
            {
                "spec_id": spec_id,
                "description": desc_text,
                "card_number": card_number,
                "base_name": base_name,
                "variant_tag": variant_tag,
                "grades": grades,
            }
        )
    return rows


def sync_all_psa_prices(limit=None, slug_contains=None):
    with db.connection() as conn:
        sets = [dict(r) for r in conn.execute("SELECT * FROM psa_sets ORDER BY year, slug").fetchall()]

    if slug_contains:
        sets = [s for s in sets if slug_contains in s["slug"]]
    if limit:
        sets = sets[:limit]

    if not sets:
        print("No PSA sets to scrape - run psa_catalog.sync_psa_pokemon_sets() first.")
        return 0, 0

    client = PsaClient()
    now = datetime.now(timezone.utc).isoformat()
    total_variants = 0
    total_prices = 0
    failed = []

    for i, psa_set in enumerate(sets, start=1):
        try:
            rows = scrape_set(client, psa_set)
        except Exception as exc:  # noqa: BLE001 - one bad set shouldn't kill the run
            print(f"  [WARN] failed set '{psa_set['slug']}' ({psa_set['psa_set_id']}): {exc}")
            failed.append(psa_set["slug"])
            continue

        with db.connection() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO psa_variants (psa_spec_id, psa_set_id, description, card_number,
                                                base_name, variant_tag, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(psa_spec_id) DO UPDATE SET
                        description=excluded.description,
                        card_number=excluded.card_number,
                        base_name=excluded.base_name,
                        variant_tag=excluded.variant_tag,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        row["spec_id"],
                        psa_set["psa_set_id"],
                        row["description"],
                        row["card_number"],
                        row["base_name"],
                        row["variant_tag"],
                        now,
                    ),
                )
                total_variants += 1
                for grade, (price, trend) in row["grades"].items():
                    conn.execute(
                        """
                        INSERT INTO psa_prices (psa_spec_id, grade, price, trend, scraped_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row["spec_id"], grade, price, trend, now),
                    )
                    total_prices += 1

            conn.execute(
                "UPDATE psa_sets SET last_crawled_at = ? WHERE psa_set_id = ?",
                (now, psa_set["psa_set_id"]),
            )

        if i % 10 == 0 or i == len(sets):
            print(f"  ...{i}/{len(sets)} sets scraped ({total_variants} variants, {total_prices} price points so far)")

    print(
        f"PSA price sync complete: {total_variants} variant rows, {total_prices} price points "
        f"across {len(sets) - len(failed)}/{len(sets)} sets."
    )
    if failed:
        print(f"  Failed sets ({len(failed)}): {', '.join(failed)}")
    return total_variants, total_prices


if __name__ == "__main__":
    db.init_db()
    sync_all_psa_prices()
