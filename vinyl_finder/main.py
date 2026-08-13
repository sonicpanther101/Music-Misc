"""
Main script: pulls your Last.fm top artists/albums, checks Discogs and
JB Hi-Fi NZ for vinyl pricing, and writes everything to a CSV.

Usage:
    python main.py
    python main.py --debug-jbhifi      # print raw JB Hi-Fi responses (for
                                          # fixing the scraper if their site
                                          # structure changes)
    python main.py --artists 20         # override TOP_N_ARTISTS for a quick
                                          # test run before doing the full one

PLEASE READ before trusting the Discogs numbers in your CSV: see the big
docstring at the top of discogs_client.py. Short version - Discogs' API
gives no reliable way to know if the cheapest listing actually ships to NZ.
`discogs_global_floor_price_nzd` is explicitly NOT used for scoring or
best-price comparisons for that reason; `discogs_price_suggestion_nzd` (a
sales-history estimate) is used instead as the working number, and
`discogs_url` is there for you to manually verify the real listing and
shipping before buying.
"""

import sys
import csv
import argparse

import config
from lastfm_client import LastFmClient, LastFmError
from discogs_client import DiscogsClient, DiscogsError
from jbhifi_client import JBHiFiClient
from currency import CurrencyConverter
from scorer import compute_scores


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--debug-jbhifi", action="store_true",
                    help="print raw JB Hi-Fi search responses for debugging")
    p.add_argument("--artists", type=int, default=None,
                    help="override TOP_N_ARTISTS, e.g. --artists 10 for a quick test")
    p.add_argument("--skip-jbhifi", action="store_true",
                    help="skip JB Hi-Fi entirely (e.g. if it's broken and you just want Discogs data)")
    p.add_argument("--skip-discogs", action="store_true",
                    help="skip Discogs entirely")
    return p.parse_args()


def main():
    args = parse_args()

    if not config.LASTFM_API_KEY:
        sys.exit("ERROR: set LASTFM_API_KEY in config.py first.")
    if not config.DISCOGS_TOKEN and not args.skip_discogs:
        sys.exit("ERROR: set DISCOGS_TOKEN in config.py first (or run with --skip-discogs).")

    top_n = args.artists or config.TOP_N_ARTISTS

    lastfm = LastFmClient(config.LASTFM_API_KEY, config.LASTFM_USERNAME,
                           request_delay=config.REQUEST_DELAY_SECONDS)
    discogs = DiscogsClient(config.DISCOGS_TOKEN,
                             request_delay=config.REQUEST_DELAY_SECONDS) if not args.skip_discogs else None
    jbhifi = JBHiFiClient(config.JBHIFI_BASE_URL,
                           request_delay=config.REQUEST_DELAY_SECONDS,
                           fuzzy_threshold=config.JBHIFI_FUZZY_MATCH_THRESHOLD) if not args.skip_jbhifi else None
    currency = CurrencyConverter(base="NZD")

    print(f"Fetching top {top_n} artists for {config.LASTFM_USERNAME}...")
    try:
        top_artists = lastfm.get_top_artists(period=config.LASTFM_PERIOD, limit=top_n)
    except LastFmError as e:
        sys.exit(f"Last.fm error: {e}")
    print(f"  got {len(top_artists)} artists")

    print("Fetching your overall top albums (for per-album scrobble counts)...")
    try:
        # Pull a generously large pool so we have a good chance of covering
        # albums by all top_n artists, not just your single biggest favourite.
        top_albums_all = lastfm.get_top_albums_overall(
            period=config.LASTFM_PERIOD, limit=max(2000, top_n * 20)
        )
    except LastFmError as e:
        sys.exit(f"Last.fm error: {e}")
    print(f"  got {len(top_albums_all)} albums total")

    albums_by_artist = {}
    for al in top_albums_all:
        albums_by_artist.setdefault(al["artist"], []).append(al)
    for artist_name in albums_by_artist:
        albums_by_artist[artist_name].sort(key=lambda a: a["playcount"], reverse=True)

    rows = []
    total = len(top_artists)

    for idx, artist in enumerate(top_artists, start=1):
        artist_name = artist["name"]
        artist_scrobbles = artist["playcount"]
        print(f"[{idx}/{total}] {artist_name} ({artist_scrobbles} scrobbles)")

        artist_albums = albums_by_artist.get(artist_name, [])
        if not artist_albums:
            # We have no album-level scrobble data for this artist (can
            # happen with the limited pool size) - still worth checking
            # shops using just the artist name, but album_scrobbles=None.
            artist_albums = [{"artist": artist_name, "album": None, "playcount": None}]
        else:
            artist_albums = artist_albums[:config.ALBUMS_PER_ARTIST]

        for album_info in artist_albums:
            album_name = album_info["album"]
            album_scrobbles = album_info["playcount"]

            row = {
                "artist": artist_name,
                "album": album_name or "(any/unspecified)",
                "artist_scrobbles": artist_scrobbles,
                "album_scrobbles": album_scrobbles,
                "lastfm_artist_url": artist.get("url"),
                "discogs_release_title": None,
                "discogs_release_id": None,
                "discogs_url": None,
                "discogs_global_floor_price_usd": None,
                "discogs_global_floor_price_nzd": None,
                "discogs_num_for_sale_global": None,
                "discogs_price_suggestion_currency": None,
                "discogs_price_suggestion_value": None,
                "discogs_price_suggestion_nzd": None,
                "jbhifi_title": None,
                "jbhifi_price_nzd": None,
                "jbhifi_match_score": None,
                "jbhifi_url": None,
                "jbhifi_in_stock": None,
                "jbhifi_est_total_nzd": None,
                "best_price_nzd": None,
                "best_source": None,
            }

            search_album = album_name or artist_name

            # ---------------- Discogs ----------------
            if discogs:
                try:
                    result = discogs.search_release(
                        artist_name, search_album, format_=config.DISCOGS_FORMAT
                    )
                    if result:
                        release_id = result.get("id")
                        row["discogs_release_title"] = result.get("title")
                        row["discogs_release_id"] = release_id
                        row["discogs_url"] = "https://www.discogs.com" + result.get("uri", "")

                        # GLOBAL FLOOR - explicitly NOT used for scoring or
                        # best_price_nzd. See discogs_client.py module
                        # docstring: this can be a listing that doesn't even
                        # ship to NZ, so it's reference-only.
                        details = discogs.get_release_details(release_id)
                        floor_usd = details.get("lowest_price")
                        row["discogs_global_floor_price_usd"] = floor_usd
                        row["discogs_num_for_sale_global"] = details.get("num_for_sale")
                        if floor_usd:
                            row["discogs_global_floor_price_nzd"] = currency.to_nzd(floor_usd, "USD")

                        # Sales-history price estimate - used as the working
                        # Discogs number for scoring, since (unlike the
                        # floor) it isn't anchored to one possibly-unshippable
                        # outlier listing. Still an ESTIMATE, not a quote -
                        # discogs_url is there to verify before buying.
                        suggestion = discogs.get_price_suggestion(
                            release_id, config.DISCOGS_CONDITION_FOR_SUGGESTION
                        )
                        if suggestion:
                            row["discogs_price_suggestion_currency"] = suggestion.get("currency")
                            row["discogs_price_suggestion_value"] = suggestion.get("value")
                            row["discogs_price_suggestion_nzd"] = currency.to_nzd(
                                suggestion.get("value"), suggestion.get("currency", "USD")
                            )
                except DiscogsError as e:
                    print(f"    Discogs error for {artist_name} - {search_album}: {e}")

            # ---------------- JB Hi-Fi NZ ----------------
            if jbhifi:
                try:
                    matches = jbhifi.search(artist_name, search_album, debug=args.debug_jbhifi)
                    if matches:
                        best = matches[0]
                        row["jbhifi_title"] = best["title"]
                        row["jbhifi_price_nzd"] = best.get("price_nzd")
                        row["jbhifi_match_score"] = best.get("match_score")
                        row["jbhifi_url"] = best.get("url")
                        row["jbhifi_in_stock"] = best.get("in_stock")
                        if best.get("price_nzd"):
                            ship = config.JBHIFI_FLAT_SHIPPING_NZD
                            if (config.JBHIFI_FREE_SHIPPING_THRESHOLD
                                    and best["price_nzd"] >= config.JBHIFI_FREE_SHIPPING_THRESHOLD):
                                ship = 0
                            row["jbhifi_est_total_nzd"] = round(best["price_nzd"] + ship, 2)
                except Exception as e:
                    print(f"    JB Hi-Fi error for {artist_name} - {search_album}: {e}")

            # ---------------- pick the "best" estimated price across sources ----------------
            # IMPORTANT: this is a comparison of an EXACT JB Hi-Fi listed
            # price against an ESTIMATED Discogs sales-history price - not
            # two equally-firm numbers. Always click discogs_url and verify
            # the real listing/shipping before treating Discogs as cheaper.
            candidates = []
            if row["jbhifi_est_total_nzd"]:
                candidates.append(("JB Hi-Fi NZ", row["jbhifi_est_total_nzd"]))
            if row["discogs_price_suggestion_nzd"]:
                candidates.append(("Discogs (estimate, verify before buying)",
                                    row["discogs_price_suggestion_nzd"]))
            if candidates:
                candidates.sort(key=lambda c: c[1])
                row["best_source"], row["best_price_nzd"] = candidates[0]

            rows.append(row)

    print(f"\nCollected {len(rows)} artist/album combinations. Scoring...")
    compute_scores(rows)

    write_csv(rows, config.OUTPUT_CSV)
    print(f"\nDone! Wrote {len(rows)} rows to {config.OUTPUT_CSV}")
    print("Sort by 'value_score' (descending) for a suggested starting point,")
    print("or by 'best_price_nzd' (ascending) for cheapest-first.")
    print("\nReminder: discogs_price_suggestion_nzd is an ESTIMATE, not a live")
    print("quote, and discogs_global_floor_price_nzd may not ship to NZ at all.")
    print("Click discogs_url and check the real listing before buying.")


def write_csv(rows, path):
    if not rows:
        return
    fieldnames = [
        "artist", "album",
        "artist_scrobbles", "album_scrobbles",
        "value_score", "cost_per_artist_scrobble", "cost_per_album_scrobble",
        "best_source", "best_price_nzd",
        "jbhifi_title", "jbhifi_price_nzd", "jbhifi_est_total_nzd",
        "jbhifi_match_score", "jbhifi_in_stock", "jbhifi_url",
        "discogs_release_title",
        "discogs_price_suggestion_nzd", "discogs_price_suggestion_value",
        "discogs_price_suggestion_currency",
        "discogs_global_floor_price_usd", "discogs_global_floor_price_nzd",
        "discogs_num_for_sale_global",
        "discogs_url", "lastfm_artist_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
