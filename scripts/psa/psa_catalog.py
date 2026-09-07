"""Finds every Pokemon set in PSA's public price guide.

PSA's Non-Sports/TCG category page lists every set it has (all TCGs, all
years) with a direct link. There's no pagination on it - we just filter the
links for the "poke-mon" slug pattern PSA uses for Pokemon sets.
"""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import config, db
from .psa_client import PsaClient

SET_LINK_RE = re.compile(r"^/priceguide/non-sports-tcg-card-values/([a-z0-9-]+)/(\d+)$")


def sync_psa_pokemon_sets():
    client = PsaClient()
    resp = client.get(config.PSA_CATEGORY_URL)
    soup = BeautifulSoup(resp.text, "html.parser")

    now = datetime.now(timezone.utc).isoformat()
    found = 0

    with db.connection() as conn:
        for a in soup.find_all("a", href=True):
            m = SET_LINK_RE.match(a["href"])
            if not m:
                continue
            slug, psa_set_id = m.groups()
            if "poke-mon" not in slug and "pokemon" not in slug:
                continue

            year_match = re.match(r"^(\d{4})-", slug)
            year = int(year_match.group(1)) if year_match else None
            is_japanese = 1 if "japanese" in slug else 0
            link_text = a.get_text(strip=True)
            display_name = link_text if link_text else slug.replace("-", " ").title()
            url = config.PSA_BASE_URL + a["href"]

            conn.execute(
                """
                INSERT INTO psa_sets (psa_set_id, slug, display_name, year, url, is_japanese, last_crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(psa_set_id) DO UPDATE SET
                    slug=excluded.slug,
                    display_name=excluded.display_name,
                    year=excluded.year,
                    url=excluded.url,
                    is_japanese=excluded.is_japanese,
                    last_crawled_at=excluded.last_crawled_at
                """,
                (psa_set_id, slug, display_name, year, url, is_japanese, now),
            )
            found += 1

    print(f"PSA Pokemon catalog sync complete: {found} sets found.")
    return found


if __name__ == "__main__":
    db.init_db()
    sync_psa_pokemon_sets()
