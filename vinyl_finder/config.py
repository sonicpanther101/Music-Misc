"""
Configuration for the vinyl finder script.

Fill in your API keys below. Both are free and take ~2 minutes to get:

  Last.fm API key:
    https://www.last.fm/api/account/create
    (just fill in any app name/description - you only need the "API key"
    field that appears after, not the "shared secret")

  Discogs personal access token:
    Log in to discogs.com, then go to:
    https://www.discogs.com/settings/developers
    Click "Generate new token"

Nothing else needs an account - JB Hi-Fi NZ is scraped (no login needed)
and currency conversion uses Frankfurter (frankfurter.dev), which needs
no key at all.
"""

# ---- Required: your details ----
LASTFM_API_KEY = "82370bab7dde52be6cb06948c0897741"          # paste your Last.fm API key here
LASTFM_USERNAME = "sonicpanther101"   # your last.fm username

DISCOGS_TOKEN = "MUjfKKirKbaTLgdVCUhrgciLdCOsESEIMuePObiV"           # paste your Discogs personal access token here

# ---- Search scope ----
TOP_N_ARTISTS = 100          # how many of your top artists to check
ALBUMS_PER_ARTIST = 5        # how many top albums per artist to check
                              # (set high, e.g. 999, to check "all" albums
                              # Last.fm has scrobbles for, per artist)

LASTFM_PERIOD = "overall"    # overall | 7day | 1month | 3month | 6month | 12month

# ---- Discogs search settings ----
DISCOGS_FORMAT = "Vinyl"     # what format to search for
# Condition to use when pulling a Discogs *price suggestion* (separate from
# the live "for sale" listing price, which is condition-agnostic).
# One of: "Mint (M)", "Near Mint (NM or M-)", "Very Good Plus (VG+)",
#         "Very Good (VG)", "Good Plus (G+)", "Good (G)", "Fair (F)", "Poor (P)"
DISCOGS_CONDITION_FOR_SUGGESTION = "Very Good Plus (VG+)"

# discogs_nz_price_nzd in the CSV is scraped directly from Discogs' own
# marketplace page with currency=NZD, for listings NOT marked "Unavailable
# in New Zealand" - so it should already reflect a real, NZ-shippable price.
# HOWEVER: Discogs' page shows shipping cost separately per-listing (it
# varies seller to seller) and adds "GST may be applied at checkout" for
# overseas sellers - neither of those is captured in this single number.
# Treat discogs_nz_price_nzd as "the item price, NZ-shippable, before this
# seller's shipping fee and possible GST" - click discogs_nz_listing_url to
# see the real total before buying.

# ---- JB Hi-Fi NZ settings ----
JBHIFI_BASE_URL = "https://www.jbhifi.co.nz"
JBHIFI_FUZZY_MATCH_THRESHOLD = 72   # 0-100, lower = more loose matches shown
JBHIFI_FREE_SHIPPING_THRESHOLD = 0  # set to e.g. 100 if you know their current
                                      # free-shipping order minimum; 0 disables
JBHIFI_FLAT_SHIPPING_NZD = 0.00     # set to JB's standard delivery fee if you
                                      # want it included even on single items
                                      # (check jbhifi.co.nz/pages/shipping)

# ---- Output ----
OUTPUT_CSV = "vinyl_report.csv"
REQUEST_DELAY_SECONDS = 1.0   # politeness delay between HTTP requests -
                                # please don't set this to 0, especially for
                                # JB Hi-Fi's site (they're not an API and we
                                # don't want to hammer them)
