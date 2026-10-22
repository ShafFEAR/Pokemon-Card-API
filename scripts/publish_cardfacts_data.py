"""Scrapes PSA CardFacts most-recent sale prices and publishes data/psa-cardfacts/.

Same shape as publish_psa_data.py: a throwaway scratch db, then the current
snapshot overwrites data/psa-cardfacts/*.json. Meant to be run monthly by
.github/workflows/refresh-cardfacts-data.yml, which commits the result if
changed.

Usage:
    py -3 scripts/publish_cardfacts_data.py [--limit N]   (N card pages, for a quick test)
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from psa import cardfacts_scraper, config, db, matcher, mirror_client  # noqa: E402
from psa.cardfacts_export import export  # noqa: E402
from psa.psa_client import PsaClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "psa-cardfacts"

# Own scratch db, so a local run can't clobber a Price Guide run's.
config.DB_PATH = Path(tempfile.gettempdir()) / "cardfacts_publish_scratch.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only scrape the first N card pages (testing)")
    args = parser.parse_args()

    config.DB_PATH.unlink(missing_ok=True)
    db.init_db()
    client = PsaClient()

    print("== 1/5 Syncing card list from GitHub Pages mirror ==")
    mirror_client.sync_cards()

    print("\n== 2/5 Syncing CardFacts Pokemon sets ==")
    pokemon_sets = cardfacts_scraper.sync_pokemon_sets(client)

    print("\n== 3/5 Reading set checklists ==")
    cards, total_entries = cardfacts_scraper.sync_set_checklists(client, pokemon_sets)

    print("\n== 4/5 Scraping card pages (~1 request/second) ==")
    prices = cardfacts_scraper.scrape_card_prices(client, cards, limit=args.limit)

    print("\n== 5/5 Matching mirror cards to CardFacts pages ==")
    matcher.match_all()

    print(f"\n== Exporting to {OUT_DIR} ==")
    export(OUT_DIR, prices, cards, total_entries)

    config.DB_PATH.unlink(missing_ok=True)
    print("\nDone.")


if __name__ == "__main__":
    main()
