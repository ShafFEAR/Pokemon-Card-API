"""Scrapes PSA's Price Guide fresh and publishes a snapshot to data/psa/.

Runs the whole pipeline in one shot against a throwaway scratch db (nothing
persisted between runs - see scripts/psa/config.py) and overwrites
data/psa/*.json with the current snapshot. Meant to be run by
.github/workflows/refresh-psa-data.yml, which commits the result if changed -
each such commit is effectively a dated price-history snapshot.

Usage:
    py -3 scripts/publish_psa_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from psa import config, db, matcher, mirror_client, psa_catalog, psa_scraper  # noqa: E402
from psa.export import export  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "psa"


def main():
    config.DB_PATH.unlink(missing_ok=True)

    print("== 1/4 Syncing card list from GitHub Pages mirror ==")
    db.init_db()
    mirror_client.sync_cards()

    print("\n== 2/4 Syncing PSA Pokemon set catalog ==")
    psa_catalog.sync_psa_pokemon_sets()

    print("\n== 3/4 Scraping PSA prices (~1 request/second, so this takes a few minutes) ==")
    psa_scraper.sync_all_psa_prices()

    print("\n== 4/4 Matching mirror cards to PSA variants ==")
    matcher.match_all()

    print(f"\n== Exporting to {OUT_DIR} ==")
    export(OUT_DIR)

    config.DB_PATH.unlink(missing_ok=True)
    print("\nDone.")


if __name__ == "__main__":
    main()
