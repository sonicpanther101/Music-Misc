# Vinyl Finder

Checks your Last.fm top artists/albums against Discogs and JB Hi-Fi NZ for
vinyl pricing, and spits out a CSV you can sort/filter/pivot however you like.

## Setup

```bash
pip install -r requirements.txt
```

Then edit `config.py`:

1. **Last.fm API key** - https://www.last.fm/api/account/create (instant,
   just needs an app name/description)
2. **Discogs token** - log in to discogs.com, go to
   https://www.discogs.com/settings/developers, click "Generate new token"
3. Set `LASTFM_USERNAME` to your username (defaults to `sonicpanther101`)

## Running it

```bash
# quick test with just 5 artists, before committing to a full run
python main.py --artists 5

# full run
python main.py

# if JB Hi-Fi's site structure has changed and matches look wrong/empty,
# this dumps the raw responses so you can see what's actually coming back
python main.py --artists 3 --debug-jbhifi

# Discogs or JB Hi-Fi down/broken? skip one and still get the other
python main.py --skip-jbhifi
python main.py --skip-discogs
```

Output goes to `vinyl_report.csv` (configurable in `config.py`).

## Why "search by artist/album" rather than "download the whole catalogue"

You asked which approach is better - here's the reasoning:

- **Discogs has ~17 million releases.** There's no practical way to pull
  "the whole catalogue" and match it locally; their own monthly data dumps
  are multi-GB XML files meant for bulk database imports, not this use case.
  Targeted search (artist + album) is the only sane approach here, and it's
  what their API is actually built for.
- **JB Hi-Fi NZ has no public catalogue feed at all** (no API, no data dump).
  The only way in is their on-site search, so "search by artist/album" isn't
  really optional for them - it's the only available door.

So: per-artist/per-album targeted lookups it is. With top 100 artists x 3
albums each, that's up to 300 lookups per shop - a few minutes, not hours.

## Important limitations (please read before trusting the numbers)

**JB Hi-Fi NZ has no API - this scrapes their search, and on the first real
run it found 0 matches.** The debug output showed JB Hi-Fi's search page IS
returning real results ("604 results found" etc.) but my HTML parser
couldn't pull anything out of the markup - I built that parser blind,
without ever seeing their real page, and it didn't match their actual
structure. **This still needs a fix.** The fastest way to get it working:

1. Run `python main.py --artists 1 --debug-jbhifi 2>&1 | tee jbhifi_debug.txt`
2. Open `jbhifi_debug.txt` and find one of the `[DEBUG] HTML search status=200`
   blocks - it'll have the full page HTML (this run only printed the first
   1500 characters; bump the slice in `jbhifi_client.py`'s `debug` prints
   if you need more)
3. Send me that file/output and I'll fix the selectors in `jbhifi_client.py`
   directly - the rest of the script doesn't need to change.

Until that's fixed, the CSV's JB Hi-Fi columns will be blank and
`best_source`/`best_price_nzd` will just reflect Discogs.

**Discogs pricing: fixed to use real NZ-shippable prices, not the global
lowest.** Earlier testing surfaced a real problem: Discogs' API field
`lowest_price` is the cheapest listing *anywhere in the world*, including
sellers who explicitly don't ship to New Zealand - in one real test case,
the API said $28.55 USD while the actual cheapest NZ-shippable copy was
$119.99 USD (≈NZ$238.91). That's not a rounding error, it's a different
listing entirely.

The fix: there's no documented API for "live listings filtered by ships-to
-country" (that existed unofficially as `marketplace/search` and Discogs
has explicitly shut it down for third parties), but the public marketplace
webpage at `discogs.com/sell/release/{id}?currency=NZD` - the same page you'd
browse by hand - is fetchable and parseable. The script now scrapes that
page directly and explicitly skips any listing marked "Unavailable in New
Zealand," so `discogs_nz_price_nzd` should be a real, buyable number. The
old global figure is kept too, renamed `discogs_global_lowest_price_nzd`,
purely as a "how much cheaper is the rest of the world" reference column -
**it is never used for `best_price_nzd` or the value score.**

This is HTML-page scraping rather than an API contract, so it's a bit more
fragile than the rest of the script. If `discogs_nz_price_nzd` comes back
empty a lot, run with `--debug-discogs` on a couple of artists and check
the printed output - the parsing logic is isolated in
`discogs_client.py`'s `get_cheapest_nz_listing()`.

One more wrinkle visible on the real page: Discogs shows "+shipping" and
"+GST GST may be applied at checkout" separately per listing - the scraped
price is the item price shown on that page, not necessarily the exact
final checkout total. `discogs_nz_listing_url` links straight to the
specific listing so you can confirm the real total before buying.

**Currency conversion** uses Frankfurter (api.frankfurter.dev) - free,
no key, sourced from European Central Bank daily reference rates. Updates
once per weekday, so don't expect it to track intraday FX swings.

**Per-album scrobble counts**: Last.fm's API has no "top albums for THIS
artist" endpoint - only "top albums overall" and "top artists overall"
separately. This script pulls a large pool of your overall top albums
(2000+, or `top_n_artists * 20`, whichever's bigger) and matches them back
to each top artist client-side. If an artist you scrobble a lot has scattered
listening across many lesser albums rather than 2-3 big ones, some of their
albums might not be in the pool - in that case `album_scrobbles` will show
blank and the row falls back to a name-only search.

## The "value_score" formula

It's deliberately simple and fully visible in `scorer.py` - not a black box.
Roughly: `(weighted scrobble interest) / sqrt(price)`. Scrobbles are
normalized 0-1 against your dataset's max so one giant favourite doesn't
flatten everyone else's score. Price uses a square-root curve so a $20
difference matters more at the cheap end than the expensive end.

This is a *starting point*, not a verdict - all the raw numbers
(`artist_scrobbles`, `album_scrobbles`, `best_price_nzd`, etc.) are their own
CSV columns, so pull it into Excel/Sheets and build your own formula or
pivot table if this one doesn't match how you actually think about it.

## Tuning knobs (all in `config.py`)

| Setting | What it does |
|---|---|
| `TOP_N_ARTISTS` | how many top artists to check |
| `ALBUMS_PER_ARTIST` | how many albums per artist |
| `LASTFM_PERIOD` | overall vs last 12 months etc. |
| `DISCOGS_CONDITION_FOR_SUGGESTION` | which condition grade to price-check for the "fair value" reference column |
| `JBHIFI_FUZZY_MATCH_THRESHOLD` | lower = more loose/approximate matches shown |
| `JBHIFI_FREE_SHIPPING_THRESHOLD` / `JBHIFI_FLAT_SHIPPING_NZD` | set if you know JB's current shipping policy |
| `REQUEST_DELAY_SECONDS` | politeness delay between requests - please don't zero this out, especially for JB Hi-Fi and the Discogs marketplace page (it's not an API, be a good citizen) |

## A note on JB Hi-Fi's shipping policy

I didn't hardcode a shipping fee/threshold because retailer shipping
policies change and I didn't want to bake in a guess as fact. Check
https://www.jbhifi.co.nz/pages/shipping for their current rates and set
`JBHIFI_FLAT_SHIPPING_NZD` / `JBHIFI_FREE_SHIPPING_THRESHOLD` accordingly.
