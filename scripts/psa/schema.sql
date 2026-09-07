PRAGMA foreign_keys = ON;

-- Card identities, refreshed from the ShafFEAR/Pokemon-Card-API GitHub Pages mirror
-- (which itself mirrors pokemontcg.io). Overwritten in place on each mirror sync.
CREATE TABLE IF NOT EXISTS cards (
    id                          TEXT PRIMARY KEY,   -- mirror card id, e.g. "base1-4"
    name                        TEXT NOT NULL,
    number                      TEXT,
    set_id                      TEXT,
    set_name                    TEXT,
    series                      TEXT,
    rarity                      TEXT,
    release_date                TEXT,
    national_pokedex_numbers    TEXT,
    image_small                 TEXT,
    tcgplayer_market            REAL,
    mirror_updated_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_cards_set_id ON cards(set_id);
CREATE INDEX IF NOT EXISTS idx_cards_name   ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_number ON cards(number);

-- Every Pokemon set found in PSA's public price guide category listing.
CREATE TABLE IF NOT EXISTS psa_sets (
    psa_set_id      TEXT PRIMARY KEY,   -- PSA's internal set id, e.g. "2432"
    slug            TEXT NOT NULL,      -- url slug, e.g. "1999-poke-mon-game"
    display_name    TEXT,
    year            INTEGER,
    url             TEXT NOT NULL,
    is_japanese     INTEGER DEFAULT 0,
    last_crawled_at TEXT
);

-- One row per priced card variant on a PSA set page (PSA prices print-run
-- variants like 1st Edition / Shadowless / Unlimited separately, which the
-- mirror does not model as separate cards - hence a variant links to at most
-- one mirror card, but a mirror card can have several variants).
CREATE TABLE IF NOT EXISTS psa_variants (
    psa_spec_id     TEXT PRIMARY KEY,   -- PSA's data-id for this row
    psa_set_id      TEXT NOT NULL REFERENCES psa_sets(psa_set_id),
    description     TEXT NOT NULL,      -- raw text, e.g. "Charizard - Holo-1st Edition"
    card_number     TEXT,
    base_name       TEXT,               -- best-effort parse, e.g. "Charizard"
    variant_tag     TEXT,               -- best-effort parse, e.g. "Holo-1st Edition"
    last_seen_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_psa_variants_set      ON psa_variants(psa_set_id);
CREATE INDEX IF NOT EXISTS idx_psa_variants_number   ON psa_variants(card_number);
CREATE INDEX IF NOT EXISTS idx_psa_variants_basename ON psa_variants(base_name);

-- Append-only price history. PSA's public price guide only publishes grades
-- 7 (NM), 8 (NM-MT), 9 (MT) and 10 (GEM-MT) - see README for why. A new sync
-- run adds new rows with a fresh scraped_at rather than overwriting, so price
-- history accumulates over time.
CREATE TABLE IF NOT EXISTS psa_prices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    psa_spec_id  TEXT NOT NULL REFERENCES psa_variants(psa_spec_id),
    grade        INTEGER NOT NULL,
    price        REAL,               -- null when PSA shows no price for this grade
    trend        TEXT,               -- 'up' / 'down' / null, from PSA's +/- markers
    scraped_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_psa_prices_spec       ON psa_prices(psa_spec_id);
CREATE INDEX IF NOT EXISTS idx_psa_prices_scraped_at ON psa_prices(scraped_at);

-- Convenience view: just the most recent price per variant/grade.
CREATE VIEW IF NOT EXISTS psa_prices_latest AS
SELECT p.*
FROM psa_prices p
JOIN (
    SELECT psa_spec_id, grade, MAX(scraped_at) AS max_scraped_at
    FROM psa_prices
    GROUP BY psa_spec_id, grade
) latest
  ON p.psa_spec_id = latest.psa_spec_id
 AND p.grade       = latest.grade
 AND p.scraped_at  = latest.max_scraped_at;

-- Best-effort linking between mirror cards and PSA variants. Rebuilt from
-- scratch on each matcher run; a variant with no row here simply has no
-- confident match yet, but its prices are still stored above regardless.
CREATE TABLE IF NOT EXISTS card_psa_match (
    card_id           TEXT NOT NULL REFERENCES cards(id),
    psa_spec_id       TEXT NOT NULL REFERENCES psa_variants(psa_spec_id),
    match_method      TEXT,
    match_confidence  REAL,
    PRIMARY KEY (card_id, psa_spec_id)
);

CREATE INDEX IF NOT EXISTS idx_match_psa_spec ON card_psa_match(psa_spec_id);
