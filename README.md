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
  psa-cardfacts/         PSA most recent sale per grade, for cards with a CardFacts page - see below
  psa-cache.json         a *different*, unrelated cache - see that section too
  pricecharting/         PriceCharting ungraded / Grade 9 / PSA 10 prices (Scarlet & Violet and Sword & Shield eras) - see below
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
  meta.json           source, scrape date, PSA's own last-updated stamp, methodology, counts
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

**How old the prices are:** `meta.json`'s `generatedAt` is only when *this repo* last
scraped. PSA's own price guide carries a single site-wide "Last updated" stamp, recorded as
`psaPricesLastUpdated` (and `psaPricesLastUpdatedText`, PSA's wording) - that is the real
age of the numbers, and it can be far behind the scrape date (it read 6/24/2025 in
October 2026, with no price changing between weekly snapshots). Show that, not
`generatedAt`, as the data's age.

**Not the same thing as `data/psa-cache.json`** right next to it - that one is an
incremental cache of real per-scan lookups against PokemonPriceTracker.com, fed by a
different app (NEW POKEMON SCANNER) via `scripts/sync_psa_cache.py`. Different source,
different update rhythm, deliberately not merged with this bulk export.

## PSA most recent sale prices (`data/psa-cardfacts/`)

The **most recent sale price** per grade (1-10 + Authentic), with its date, from PSA's
public [CardFacts](https://www.psacard.com/cardfacts) card pages - plus the average sale
price, PSA's own price and population for each grade. Unlike Auction Prices Realized,
CardFacts pages need no login. `.github/workflows/refresh-cardfacts-data.yml` runs it on
the 1st of every month (08:00 UTC) and auto-commits any changes; trigger it from the
Actions tab anytime. Takes ~25 minutes (one request per second, per PSA's robots.txt).

```
data/psa-cardfacts/
  meta.json           source, scrape date, counts, methodology
  by-card-id.json     mirror card id -> [{ cardfactsId, url, description, cardNumber,
                       psaSetName, variantTag, matchConfidence,
                       grades: {"10": { mostRecent, mostRecentDate, average, psaPrice,
                                        population, suspect? }, "9": .., "Auth": .. } }]
  unmatched.json      CardFacts cards not linked to a mirror card id (Japanese sets, odd
                       promos) - same entry shape, no matchConfidence
```

**Coverage is small:** CardFacts only exists for ~1,400 Pokemon cards PSA chose to write
up (mostly 1999-2005 WotC/early-ex era, nothing after 2020), so most mirror cards have no
entry here. That's a PSA limitation - the rest have no public "most recent price" on
psacard.com. A grade marked `"suspect": true` has a most recent sale more than 4x away
from its average (usually a mislabeled listing) - prefer `average` for those. Card
matching uses the same heuristic as `data/psa/`.

## PriceCharting prices (`data/pricecharting/`)

Ungraded, Grade 9 and PSA 10 prices from [PriceCharting](https://www.pricecharting.com/)
for every **Scarlet & Violet-era and Sword & Shield-era** card in this mirror (about 7,300
cards, 43 sets - see `meta.json`'s `bySet`), plus 108 older niche cards (McDonald's promos,
theme-deck exclusives, ...) that no other source here prices. **Prices are PriceCharting's;
each entry's `url` is the PriceCharting product page it was read from - please link back
to it when you show them, and check PriceCharting's terms before reusing the data
elsewhere.**

Why it exists: PSA's public Price Guide (`data/psa/`) has no Pokemon sets after
2021 and its published numbers are frozen, so modern cards have no PSA price at all.
PriceCharting is more recent, so a scanner can show it next to - or instead of - PSA.

```
data/pricecharting/
  meta.json           source, attribution, method, read date, per-set counts, caveats
  by-card-id.json      mirror card id -> { name, number, setName, url, ungraded,
                        grade9, psa10 }  (null = PriceCharting has no price there;
                        older entries also carry readOn, their own read date, when it
                        isn't the file-level pricesReadOn in meta.json)
  unmatched.json       cards with no PriceCharting product found (or that couldn't be
                        matched confidently), with why
```

**Different from the other two data sources in an important way**: this is a manual
snapshot (prices read 2026-10-18), not an automated bulk export. PriceCharting's own
API/CSV bulk download requires a paid subscription and none was used: the set listing
pages were loaded one at a time in a normal browser session and the visible price
columns copied (checksum-verified) and matched to card ids by set + collector number +
name. So unlike `data/sets/` and `data/psa/` there's no scheduled workflow keeping it
fresh - redo the pages when it goes stale, or extend coverage to newer sets
(Mega Evolution-era sets aren't included yet).

Only the plain card is recorded per id (not reverse-holo / Poke Ball / Master Ball /
stamped / prize-pack / jumbo variants), and Grade 9 / PSA 10 for rarely-traded cards can
rest on a few sales, so big jumps (e.g. a $0.25 card with a $325 Grade 9) are often
thin-sample noise - see `meta.json`'s `note`.

## Known limitations

- **Price data goes stale between refreshes.** pokemontcg.io's `tcgplayer`/`cardmarket`
  blocks update frequently upstream; this mirror is only as fresh as its last run. Fine
  for identification (name/number/set), treat prices as a snapshot, not live.
- **No fuzzy search.** `by-name.json` keys are exact-normalized (trimmed, lowercased)
  card names — same matching precision as querying pokemontcg.io by name, not better.
- **Card images are linked, not mirrored.** `images.small`/`images.large` URLs point at
  `images.pokemontcg.io` directly (a separate CDN from the rate-limited API) — no reason
  to duplicate that storage here.
