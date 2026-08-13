"""
JB Hi-Fi NZ client - searches jbhifi.co.nz for vinyl matching an artist/album.

JB Hi-Fi NZ has no public API, so this polls their storefront search.
Their site runs on Shopify (URLs follow the /collections/... pattern), so we
use Shopify's standard search endpoint, requesting JSON where possible.

IMPORTANT: Shopify storefronts can be configured differently store-to-store,
and JB Hi-Fi's site structure can change without notice. This module is
written defensively:
  - it tries the JSON-friendly search endpoint first
  - if that fails or comes back empty/malformed, it falls back to parsing
    the HTML search results page
  - if BOTH fail, it returns an empty list and logs a warning rather than
    crashing the whole run

If JB changes their site and this stops working, run with --debug-jbhifi
once (see main.py) to dump the raw response for inspection, then this file
is the one to fix - the search()/parse logic is isolated here.
"""

import time
import json
import re
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz


class JBHiFiClient:
    def __init__(self, base_url, request_delay=1.0, fuzzy_threshold=72):
        self.base_url = base_url.rstrip("/")
        self.request_delay = request_delay
        self.fuzzy_threshold = fuzzy_threshold
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })

    def search(self, artist, album, debug=False):
        """
        Search JB Hi-Fi NZ for products matching "artist album" and
        return a list of candidate matches:
          [{title, price_nzd, url, match_score, in_stock}, ...]
        Sorted by fuzzy match score descending.
        """
        query = f"{artist} {album} vinyl"
        candidates = self._search_via_json(query, debug=debug)
        if not candidates:
            candidates = self._search_via_html(query, debug=debug)

        target = f"{artist} {album}".lower()
        scored = []
        for c in candidates:
            score = fuzz.token_set_ratio(target, c["title"].lower())
            if score >= self.fuzzy_threshold:
                c["match_score"] = score
                scored.append(c)

        scored.sort(key=lambda x: x["match_score"], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Strategy 1: Shopify's predictive-search / search.json style endpoint
    # ------------------------------------------------------------------
    def _search_via_json(self, query, debug=False):
        endpoint = f"{self.base_url}/search/suggest.json"
        params = {
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 10,
            "resources[options][unavailable_products]": "show",
        }
        try:
            resp = self.session.get(endpoint, params=params, timeout=20)
            time.sleep(self.request_delay)
            if debug:
                print(f"[DEBUG] JSON search status={resp.status_code} url={resp.url}")
                print(resp.text[:2000])
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            if debug:
                print(f"[DEBUG] JSON search failed: {e}")
            return []

        results = []
        products = data.get("resources", {}).get("results", {}).get("products", [])
        for p in products:
            price = self._extract_price(p.get("price") or p.get("price_max"))
            results.append({
                "title": p.get("title", ""),
                "price_nzd": price,
                "url": self.base_url + p.get("url", "") if p.get("url", "").startswith("/") else p.get("url", ""),
                "in_stock": p.get("available", True),
            })
        return results

    # ------------------------------------------------------------------
    # Strategy 2: fall back to parsing the regular HTML search page
    # ------------------------------------------------------------------
    def _search_via_html(self, query, debug=False):
        endpoint = f"{self.base_url}/search"
        params = {"q": query, "type": "product"}
        try:
            resp = self.session.get(endpoint, params=params, timeout=20)
            time.sleep(self.request_delay)
            if debug:
                print(f"[DEBUG] HTML search status={resp.status_code} url={resp.url}")
                print(resp.text[:3000])
                # The page clearly contains real results ("N results found"
                # in the <title>) even when our selectors below find
                # nothing - so dump the FULL page to disk on every debug
                # run, overwriting each time. Send this file back if
                # results still come back empty - it's the fastest way to
                # fix the selectors without guessing blind again.
                try:
                    with open("jbhifi_debug_last_page.html", "w", encoding="utf-8") as f:
                        f.write(resp.text)
                    print("[DEBUG] full page saved to jbhifi_debug_last_page.html")
                except OSError:
                    pass
            if resp.status_code != 200:
                return []
        except requests.RequestException as e:
            if debug:
                print(f"[DEBUG] HTML search failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # Strategy 2a: plain anchor tags linking to /products/ (older/simpler
        # Shopify themes render search results as straightforward links).
        candidates = soup.select("a[href*='/products/']")
        seen_urls = set()
        for a in candidates:
            href = a.get("href", "")
            if not href or href in seen_urls:
                continue
            title = a.get("title") or a.get_text(strip=True)
            if not title or len(title) < 2:
                title_el = a.find(["h2", "h3", "span", "p"])
                title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            seen_urls.add(href)

            price = None
            container = a.find_parent(["li", "div"])
            if container:
                price_match = re.search(r"\$[\d,]+\.\d{2}", container.get_text())
                if price_match:
                    price = self._extract_price(price_match.group(0))

            full_url = href if href.startswith("http") else self.base_url + href
            results.append({
                "title": title,
                "price_nzd": price,
                "url": full_url,
                "in_stock": True,
            })

        if results:
            return results

        # Strategy 2b: many modern Shopify themes (and JB Hi-Fi's is a
        # newer/custom one, given strategy 2a found nothing despite real
        # results existing) hydrate search results client-side from a JSON
        # blob embedded in a <script> tag rather than rendering plain <a>
        # links server-side. Scan all <script> tags for anything that looks
        # like a list of product objects (has "title" and a price-ish key
        # near each other) and pull matches out with a loose regex - this
        # is a best-effort fallback, not a guarantee.
        for script in soup.find_all("script"):
            script_text = script.string or script.get_text() or ""
            if '"title"' not in script_text and "'title'" not in script_text:
                continue
            # look for {"title":"...", ... "price":...} - ish fragments
            for m in re.finditer(
                r'"title"\s*:\s*"([^"]{2,150})".{0,300}?"price"\s*:\s*"?([\d.]+)"?',
                script_text,
            ):
                title, price_raw = m.group(1), m.group(2)
                results.append({
                    "title": title,
                    "price_nzd": self._extract_price(price_raw),
                    "url": None,
                    "in_stock": True,
                })

        if debug:
            print(f"[DEBUG] strategy 2a found 0 results, strategy 2b (script-tag scan) found {len(results)}")

        return results

    @staticmethod
    def _extract_price(raw):
        """
        Parse a price value into NZ dollars (float).

        NOTE ON CENTS AMBIGUITY: Shopify's storefront APIs are inconsistent
        about whether `price` fields are in dollars (e.g. 54.99) or cents
        (e.g. 5499). We deliberately do NOT try to guess based on magnitude
        - a $1099.00 boxset and "1099 cents" look identical and guessing
        wrong silently corrupts the data. Instead:
          - strings containing a "." are always treated as already being
            in dollars (e.g. "$54.99", "54.99") - this covers the HTML
            fallback path, which only ever extracts $XX.XX-style text.
          - bare integers/floats with NO decimal point are passed through
            as dollars by default. If you find JB Hi-Fi's JSON endpoint is
            actually returning cents (run with --debug-jbhifi and check),
            divide by 100 in _search_via_json() where the field is read,
            rather than guessing here.
        """
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        s = re.sub(r"[^\d.]", "", str(raw))
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
