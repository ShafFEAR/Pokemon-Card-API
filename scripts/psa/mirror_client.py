"""Pulls the card catalog from the ShafFEAR/Pokemon-Card-API GitHub Pages
mirror (a static copy of pokemontcg.io) and upserts it into the `cards` table.
"""
from datetime import datetime, timezone

import requests

from . import config, db


def _get_json(session, path):
    url = f"{config.MIRROR_BASE_URL}/{path}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _best_market_price(card):
    tcgplayer = card.get("tcgplayer") or {}
    for variant_prices in (tcgplayer.get("prices") or {}).values():
        market = variant_prices.get("market")
        if market:
            return market
    return None


def sync_cards(progress_every=20):
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})

    meta = _get_json(session, "meta.json")
    sets_index = _get_json(session, "sets/index.json")
    now = datetime.now(timezone.utc).isoformat()

    total_cards = 0
    skipped_sets = 0

    with db.connection() as conn:
        for i, set_entry in enumerate(sets_index, start=1):
            set_id = set_entry["id"]
            try:
                set_data = _get_json(session, f"sets/{set_id}.json")
            except requests.HTTPError:
                skipped_sets += 1
                continue

            set_meta = set_data.get("set", {})
            for card in set_data.get("cards", []):
                conn.execute(
                    """
                    INSERT INTO cards (id, name, number, set_id, set_name, series,
                                        rarity, release_date, national_pokedex_numbers,
                                        image_small, tcgplayer_market, mirror_updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        number=excluded.number,
                        set_id=excluded.set_id,
                        set_name=excluded.set_name,
                        series=excluded.series,
                        rarity=excluded.rarity,
                        release_date=excluded.release_date,
                        national_pokedex_numbers=excluded.national_pokedex_numbers,
                        image_small=excluded.image_small,
                        tcgplayer_market=excluded.tcgplayer_market,
                        mirror_updated_at=excluded.mirror_updated_at
                    """,
                    (
                        card["id"],
                        card.get("name"),
                        card.get("number"),
                        set_id,
                        set_meta.get("name"),
                        set_meta.get("series"),
                        card.get("rarity"),
                        set_meta.get("releaseDate"),
                        str(card.get("nationalPokedexNumbers", [])),
                        (card.get("images") or {}).get("small"),
                        _best_market_price(card),
                        now,
                    ),
                )
                total_cards += 1

            if i % progress_every == 0 or i == len(sets_index):
                print(f"  ...{i}/{len(sets_index)} sets processed, {total_cards} cards so far")

    print(
        f"Mirror sync complete: {total_cards} cards from {len(sets_index) - skipped_sets} sets "
        f"({skipped_sets} sets skipped/unavailable). "
        f"Mirror meta reports {meta.get('totalCards')} cards / {meta.get('totalSets')} sets "
        f"generated at {meta.get('generatedAt')}."
    )
    return total_cards


if __name__ == "__main__":
    db.init_db()
    sync_cards()
