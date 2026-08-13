"""
Discogs client - searches for vinyl releases and pulls pricing data.

*** IMPORTANT - READ THIS BEFORE TRUSTING ANY DISCOGS PRICE IN THE CSV ***

`lowest_price` on /releases/{id} is the cheapest listing IN THE WORLD, in
ANY condition, from ANY seller - including sellers who don't ship to New
Zealand at all, or whose listing attracts GST/customs fees at checkout that
aren't reflected in the sticker price. It is NOT "the cheapest thing you can
actually buy." Real example found while testing this script: `lowest_price`
said $28.55 USD, but that seller (and the next-cheapest one) doesn't ship to
NZ - the actual cheapest *buyable* listing was $119.99 USD, more than 4x
higher.

WHY THIS CAN'T BE FIXED PROPERLY VIA THE API: Discogs has no documented,
supported endpoint that lists individual marketplace listings for a release
filtered by ships-to-country. An undocumented `/marketplace/search?release_id=`
endpoint used to allow something close to this; Discogs deliberately killed
it years ago specifically because they don't want third parties relying on
it, and their own forum staff have said scraping marketplace pages/endpoints
risks getting your requests aggressively rate-limited. So this script does
NOT attempt to scrape or reconstruct NZ-shippable listing prices. Instead,
this script gives you honestly-labeled numbers and leaves the last 30
seconds of checking to you:

  - `discogs_global_floor_price_nzd` - the /releases/{id} `lowest_price`,
     converted to NZD. This is a FLOOR, not a quote - treat it as "records
     this cheap exist somewhere," nothing more. NEVER used for scoring.
  - `discogs_price_suggestion_nzd` - Discogs' own price suggestion by
     condition grade, based on sales history (not a live listing). This is
     used as the working Discogs price estimate for scoring, since it's at
     least not anchored to a single non-shippable outlier listing - but
     it's still an estimate, not a quote.
  - `discogs_url` - always populated. Click through, check the real
     listings, and look for "Unavailable in New Zealand" tags and
     shipping cost yourself before buying - there's no way around this
     last step without authenticating as a buyer and going through
     checkout for each listing, which isn't something a script should do
     on your behalf without explicit per-purchase confirmation anyway.

What IS documented, stable, and used by this client:
  1. /database/search                      -> find release IDs
  2. /releases/{id}                          -> `lowest_price` (global floor,
                                                 see warning above) + `num_for_sale`
  3. /marketplace/price_suggestions/{id}     -> sales-history based price
                                                 estimate per condition grade
"""

import time
import requests

API_ROOT = "https://api.discogs.com"
USER_AGENT = "VinylFinderScript/1.0 (personal use)"


class DiscogsError(Exception):
    pass


class DiscogsClient:
    def __init__(self, token, request_delay=1.0):
        self.token = token
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Authorization": f"Discogs token={token}",
        })

    def _get(self, path, **params):
        url = f"{API_ROOT}{path}"
        resp = self.session.get(url, params=params, timeout=20)
        time.sleep(self.request_delay)
        if resp.status_code == 429:
            # rate limited - back off and retry once
            time.sleep(5)
            resp = self.session.get(url, params=params, timeout=20)
            time.sleep(self.request_delay)
        if resp.status_code != 200:
            raise DiscogsError(f"Discogs API HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def search_release(self, artist, album, format_="Vinyl"):
        """
        Search Discogs for a release matching artist + album title.
        Returns the best-match result dict (or None), preferring results
        with the most listings for sale (more liquid = easier to actually buy).
        """
        data = self._get(
            "/database/search",
            artist=artist,
            release_title=album,
            format=format_,
            type="release",
            per_page=10,
        )
        results = data.get("results", [])
        if not results:
            # fall back to a looser combined-text search
            data = self._get(
                "/database/search",
                q=f"{artist} {album}",
                format=format_,
                type="release",
                per_page=10,
            )
            results = data.get("results", [])
        if not results:
            return None

        # Prefer results that have more community "haves" - correlates
        # with the pressing being commonly available, easier to find a copy.
        def sort_key(r):
            return (r.get("community", {}).get("have", 0) or 0)

        results.sort(key=sort_key, reverse=True)
        return results[0]

    def get_release_details(self, release_id):
        """
        Returns full release info, including (if available):
          lowest_price (float, USD - GLOBAL floor, may not ship to NZ,
                        see module docstring) and num_for_sale (int, global).
        """
        return self._get(f"/releases/{release_id}")

    def get_price_suggestion(self, release_id, condition):
        """
        Returns Discogs' suggested price for this release at a given
        condition grade, e.g. {"currency": "USD", "value": 9.35}.
        This is a sales-history-based estimate, NOT a live listing, and is
        NOT NZ-specific. Returns None if unavailable (some releases have no
        sales history to base a suggestion on).
        """
        try:
            data = self._get(f"/marketplace/price_suggestions/{release_id}")
        except DiscogsError:
            return None
        return data.get(condition)
