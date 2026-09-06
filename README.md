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

## Known limitations

- **Price data goes stale between refreshes.** pokemontcg.io's `tcgplayer`/`cardmarket`
  blocks update frequently upstream; this mirror is only as fresh as its last run. Fine
  for identification (name/number/set), treat prices as a snapshot, not live.
- **No fuzzy search.** `by-name.json` keys are exact-normalized (trimmed, lowercased)
  card names — same matching precision as querying pokemontcg.io by name, not better.
- **Card images are linked, not mirrored.** `images.small`/`images.large` URLs point at
  `images.pokemontcg.io` directly (a separate CDN from the rate-limited API) — no reason
  to duplicate that storage here.
