"""Merges a local PSA-price cache (accumulated by NEW POKEMON SCANNER from real, live
PokemonPriceTracker lookups during actual scanning sessions) into this repo's
data/psa-cache.json, so it's shared via GitHub Pages for future sessions to fall back on
when a live lookup is rate-limited or fails.

Deliberately NOT a bulk scrape or one-time backfill - this only ever merges prices that
were genuinely looked up one at a time as real cards came up during real use, respecting
PokemonPriceTracker's own rate limits exactly as the app already does. Every entry keeps
the timestamp of when it was actually fetched; nothing here fabricates or backdates one.

Usage:
    py -3 scripts/sync_psa_cache.py <path to local psa_cache.json>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_CACHE_PATH = ROOT / "data" / "psa-cache.json"


def main():
    if len(sys.argv) != 2:
        print("Usage: py -3 scripts/sync_psa_cache.py <path to local psa_cache.json>")
        sys.exit(1)

    local_path = Path(sys.argv[1])
    local = json.loads(local_path.read_text(encoding="utf-8"))
    repo = json.loads(REPO_CACHE_PATH.read_text(encoding="utf-8")) if REPO_CACHE_PATH.exists() else {}

    added, updated = 0, 0
    for key, entry in local.items():
        existing = repo.get(key)
        if existing is None:
            added += 1
        elif entry.get("asOf", "") > existing.get("asOf", ""):
            updated += 1
        else:
            continue
        repo[key] = entry

    REPO_CACHE_PATH.write_text(json.dumps(repo, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print(f"Merged {local_path}: {added} new, {updated} updated, {len(repo)} total entries now in {REPO_CACHE_PATH}")


if __name__ == "__main__":
    main()
