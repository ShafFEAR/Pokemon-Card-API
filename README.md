# Pokemon Card Data API

A static mirror of the [pokemontcg.io](https://pokemontcg.io) card database, hosted as
plain JSON files on GitHub Pages. No server, no rate limit on your side, no API key
required to read it — you're just fetching files from a CDN.

**Why this exists:** pokemontcg.io's free tier caps out at 1,000 requests/day
unauthenticated (20,000/day with a free key), which the Pokemon card scanner projects
kept running into. This repo pulls the whole dataset once (and refreshes it on a
schedule), so lookups hit your own copy instead.

**Heads up:** pokemontcg.io's marketing site currently reads "now part of Scrydex," and
`scrydex.com` resolves to a parked domain page as of this writing (2026-09-06) — the
underlying `api.pokemontcg.io` was still fully live and returning same-day price updates
when this was built, but its long-term status is unclear. That's exactly the kind of
thing an independent mirror hedges against.

## Layout

```
data/
  meta.json              generation timestamp, totals, source info
  sets/
    index.json           every set (id, name, series, releaseDate, images, ...)
    {setId}.json         { "set": {...}, "cards": [...] } for one set, e.g. base1.json
  index/
    by-name.json         normalized card name -> [{ id, name, number, setId, setName }]
  psa/                   PSA graded-card prices - see "PSA graded-card prices" below
  psa-cache.json         a *different*, unrelated cache - see that section too
  pricecharting/         supplementary prices for cards with no other price - see below
```

Card and set objects are the raw pokemontcg.io API records, unmodified.

## Using it once hosted

Enable GitHub Pages for this repo (Settings -> Pages -> Deploy from branch -> `main` /
root), then it's just static files:

```
https://<your-username>.github.io/<repo>/data/sets/index.json
https://<your-username>.github.io/<repo>/data/sets/base1.json
https://<your-username>.github.io/<repo>/data/index/by-name.json
```

Typical lookup (name -> candidates -> full card + current price): fetch
`by-name.json` once and cache it client-side, find matches for the card name you read,
then fetch that card's `sets/{setId}.json` for full details (pricing included).

## Regenerating the data

```bash
py -3 scripts/fetch_data.py
```

Paces requests at ~1 per 2.5s to stay under pokemontcg.io's unauthenticated 30/min cap.
Takes a few minutes for the full ~20,500-card dataset. Set `POKEMONTCG_API_KEY` in the
environment to use a free pokemontcg.io key instead (higher rate limit, same output).

`.github/workflows/refresh-data.yml` runs this weekly and commits any changes
automatically, so new sets show up without manual work.

## PSA graded-card prices (`data/psa/`)

A bulk export of PSA's public [Price Guide](https://www.psacard.com/priceguide), scraped
and matched to this repo's card ids. `.github/workflows/refresh-psa-data.yml` runs it
weekly (Monday 07:00 UTC, an hour after the card-data refresh) and auto-commits any
changes - the scraper (`scripts/psa/`) and publish step (`scripts/publish_psa_data.py`)
live in this repo, ported from a separate local project (PSAPokemonTracker) that keeps
the full queryable price *history* in a local db; this repo only ever holds the latest
snapshot, so **history here means git commit history** - `git log -- data/psa/` to see
past snapshots, not a query.

```
data/psa/
  meta.json           source, scrape date, methodology, counts
  by-card-id.json     mirror card id -> [{ psaSpecId, psaSetId, description, cardNumber,
                       variantTag, matchConfidence, grades: {"7": .., "8": .., ... } }]
                       (a list, not a single object - PSA prices print-run variants like
                       1st Edition / Shadowless / Unlimited separately, so one card id can
                       have several entries)
  unmatched.json      PSA variants not confidently linked to a mirror card id (still has
                       real prices, just include psaSetSlug/psaSetName instead of a card id)
```

Only grades NM 7 / NM-MT 8 / MT 9 / GEM-MT 10 are here (and not every card has all four)
- that's the most PSA publishes without an account login. Card matching is heuristic
(see `matchConfidence`, and `meta.json`'s `matchMethod`), so treat a low-confidence entry
as a lead to verify, not a certainty. Manually trigger a refresh anytime from the Actions
tab (`workflow_dispatch`) instead of waiting for Monday.

**Not the same thing as `data/psa-cache.json`** right next to it - that one is an
incremental cache of real per-scan lookups against PokemonPriceTracker.com, fed by a
different app (NEW POKEMON SCANNER) via `scripts/sync_psa_cache.py`. Different source,
different update rhythm, deliberately not merged with this bulk export.

## PriceCharting supplementary prices (`data/pricecharting/`)

Prices for the specific cards that have **neither** a loose (TCGplayer/Cardmarket) price
in `data/sets/` **nor** a PSA price in `data/psa/` - mostly niche, low-circulation
products (McDonald's promos, theme-deck exclusives, basic energies) that those two
sources don't individually track. From [PriceCharting](https://www.pricecharting.com/).

```
data/pricecharting/
  meta.json           source, method, counts, known-caveat notes
  by-card-id.json      mirror card id -> { name, number, setName, url, ungraded,
                        grade9, psa10 }
  unmatched.json       cards that couldn't be confidently matched to one PriceCharting
                        product, with why - e.g. a card printed twice under the same
                        collector number with two different values, no way to tell
                        which from our data alone
```

**Different from the other two data sources in an important way**: this is a small,
manually-targeted, one-time lookup (124 cards, 2026-09-07), not an automated bulk export
- PriceCharting's own API/CSV bulk-download requires a paid subscription, so unlike
`data/sets/` and `data/psa/` there's no scheduled workflow keeping this fresh. Re-run
manually (look up the specific cards, rebuild the JSON) if this goes stale or you want to
extend coverage. Two entries have prices that look like thin-sample anomalies rather than
real market consensus - see `meta.json`'s `note` field before relying on those two.

## Known limitations

- **Price data goes stale between refreshes.** pokemontcg.io's `tcgplayer`/`cardmarket`
  blocks update frequently upstream; this mirror is only as fresh as its last run. Fine
  for identification (name/number/set), treat prices as a snapshot, not live.
- **No fuzzy search.** `by-name.json` keys are exact-normalized (trimmed, lowercased)
  card names — same matching precision as querying pokemontcg.io by name, not better.
- **Card images are linked, not mirrored.** `images.small`/`images.large` URLs point at
  `images.pokemontcg.io` directly (a separate CDN from the rate-limited API) — no reason
  to duplicate that storage here.
