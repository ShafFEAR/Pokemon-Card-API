"""
Pulls the full Pokemon TCG card dataset from api.pokemontcg.io and writes it
into data/ as static JSON, so it can be hosted (e.g. via GitHub Pages) and
queried without hitting pokemontcg.io's own rate limits.

Usage:
    py -3 scripts/fetch_data.py

Optional env var POKEMONTCG_API_KEY raises the source rate limit from
1000/day (30/min) to 20000/day - not required, this runs fine without one.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.pokemontcg.io/v2"
PAGE_SIZE = 250
REQUEST_DELAY_SECONDS = 2.5  # keeps us safely under the unauthenticated 30/min cap
MAX_RETRIES = 8
MAX_BACKOFF_SECONDS = 30
# Cloudflare (fronting api.pokemontcg.io) 403s the default Python urllib UA string.
USER_AGENT = "Mozilla/5.0 (compatible; OurOwnPokemonAPI/1.0; +static data mirror)"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHECKPOINT_FILE = ROOT / "scripts" / ".fetch_checkpoint.json"
API_KEY = os.environ.get("POKEMONTCG_API_KEY", "").strip()


def fetch(path: str, params: dict) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}{path}?{query}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    if API_KEY:
        req.add_header("X-Api-Key", API_KEY)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code >= 500 and attempt < MAX_RETRIES:
                backoff = min(REQUEST_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
                print(f"  ... {e.code} on attempt {attempt}, retrying in {backoff:.0f}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                backoff = min(REQUEST_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
                print(f"  ... {type(e).__name__} on attempt {attempt}, retrying in {backoff:.0f}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise
    raise last_error  # pragma: no cover


def fetch_all_sets() -> list[dict]:
    print("Fetching set list...", flush=True)
    result = fetch("/sets", {"pageSize": PAGE_SIZE})
    sets = result["data"]
    print(f"  {len(sets)} sets (totalCount={result['totalCount']})", flush=True)
    return sets


def fetch_all_cards() -> list[dict]:
    cards = []
    page = 1

    if CHECKPOINT_FILE.exists():
        checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        cards = checkpoint["cards"]
        page = checkpoint["next_page"]
        print(f"Resuming from checkpoint: {len(cards)} cards already fetched, starting at page {page}")

    while True:
        print(f"Fetching cards page {page}...", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)
        result = fetch("/cards", {"pageSize": PAGE_SIZE, "page": page})
        batch = result["data"]
        cards.extend(batch)
        total = result["totalCount"]
        print(f"  {len(cards)}/{total}", flush=True)

        if len(cards) >= total or not batch:
            break

        page += 1
        CHECKPOINT_FILE.write_text(
            json.dumps({"next_page": page, "cards": cards}), encoding="utf-8"
        )

    CHECKPOINT_FILE.unlink(missing_ok=True)
    return cards


def main():
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "sets").mkdir(exist_ok=True)
    (DATA_DIR / "index").mkdir(exist_ok=True)

    sets = fetch_all_sets()
    sets_by_id = {s["id"]: s for s in sets}

    cards = fetch_all_cards()

    cards_by_set = defaultdict(list)
    for card in cards:
        cards_by_set[card["set"]["id"]].append(card)

    name_index = defaultdict(list)
    for card in cards:
        key = card["name"].strip().lower()
        name_index[key].append({
            "id": card["id"],
            "name": card["name"],
            "number": card.get("number"),
            "setId": card["set"]["id"],
            "setName": card["set"]["name"],
        })

    for set_id, set_cards in cards_by_set.items():
        out = {"set": sets_by_id.get(set_id), "cards": set_cards}
        (DATA_DIR / "sets" / f"{set_id}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=None), encoding="utf-8"
        )

    (DATA_DIR / "sets" / "index.json").write_text(
        json.dumps(sets, ensure_ascii=False, indent=None), encoding="utf-8"
    )

    (DATA_DIR / "index" / "by-name.json").write_text(
        json.dumps(name_index, ensure_ascii=False, indent=None), encoding="utf-8"
    )

    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalSets": len(sets),
        "totalCards": len(cards),
        "source": "https://api.pokemontcg.io/v2",
        "sourceNote": (
            "pokemontcg.io's marketing site now reads 'part of Scrydex'; "
            "the API itself was still live and serving fresh price data "
            "as of this generation run. This mirror exists so lookups "
            "don't depend on that API's availability or rate limits."
        ),
    }
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nDone: {len(sets)} sets, {len(cards)} cards -> {DATA_DIR}")


if __name__ == "__main__":
    main()
