#!/usr/bin/env python3
"""
Wishlist × Last.fm cross-referencer
------------------------------------
Reads a wishlist CSV (columns: artist, album) and fetches scrobble stats
from Last.fm for each entry, writing an enriched CSV as output.

Usage:
    python wishlist_lastfm.py wishlist.csv
    python wishlist_lastfm.py wishlist.csv --out enriched.csv

Wishlist CSV format (no header row required, but supported):
    Artist Name,Album Title
    ...
"""

import argparse
import csv
import sys
import time
import json

try:
    import requests
except ImportError:
    sys.exit("Please install requests:  pip install requests")

LASTFM_USERNAME = "sonicpanther101"
LASTFM_API_KEY  = "f92a7517d4ed4c28d295cc50585278f8"   # get a free key at https://www.last.fm/api/account/create
LASTFM_BASE     = "https://ws.audioscrobbler.com/2.0/"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "wishlist-lastfm-script/1.0 (github.com/user/wishlist-lastfm)",
    "Accept": "application/json",
})

OUTPUT_FIELDS = [
    "artist",
    "album",
    "lastfm_artist_playcount",      # your total scrobbles for this artist
    "lastfm_album_playcount",       # your total scrobbles for this album
    "lastfm_album_url",             # link to the album page
    "lastfm_artist_url",            # link to the artist page
    "lastfm_album_tracks",          # number of tracks on the album (if known)
    "lastfm_status",                # ok / artist_not_found / album_not_found / error
]


# ---------------------------------------------------------------------------
# Last.fm API helpers
# ---------------------------------------------------------------------------

def _call(params: dict) -> dict:
    """Make a Last.fm API call and return the parsed JSON."""
    params = {**params, "api_key": LASTFM_API_KEY, "format": "json"}
    r = SESSION.get(LASTFM_BASE, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_artist_stats(artist: str) -> dict:
    """Return user-specific stats for an artist."""
    try:
        data = _call({
            "method": "artist.getinfo",
            "artist": artist,
            "username": LASTFM_USERNAME,
            "autocorrect": 1,
        })
        if "error" in data:
            return {"status": "artist_not_found"}
        info = data["artist"]
        return {
            "status": "ok",
            "artist_url": info.get("url", ""),
            # 'userplaycount' only present when username is passed
            "artist_playcount": info.get("stats", {}).get("userplaycount", "0"),
        }
    except Exception as e:
        return {"status": f"error: {e}"}


def get_album_stats(artist: str, album: str) -> dict:
    """Return user-specific stats for an album."""
    try:
        data = _call({
            "method": "album.getinfo",
            "artist": artist,
            "album": album,
            "username": LASTFM_USERNAME,
            "autocorrect": 1,
        })
        if "error" in data:
            return {"status": "album_not_found"}
        info = data["album"]
        tracks = info.get("tracks", {}).get("track", [])
        track_count = len(tracks) if isinstance(tracks, list) else (1 if tracks else 0)
        return {
            "status": "ok",
            "album_url": info.get("url", ""),
            "album_playcount": info.get("userplaycount", "0"),
            "album_tracks": track_count,
        }
    except Exception as e:
        return {"status": f"error: {e}"}


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

KNOWN_HEADERS = {"artist", "album", "artist name", "album title", "album name"}

def read_wishlist(path: str) -> list[dict]:
    """Read wishlist CSV; auto-detect whether first row is a header."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(1024)
        f.seek(0)
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        sys.exit("Wishlist file is empty.")

    # Detect header: if both cells of row 0 look like column names, skip it
    first = [c.strip().lower() for c in rows[0]]
    has_header = len(first) >= 2 and first[0] in KNOWN_HEADERS

    data_rows = rows[1:] if has_header else rows
    entries = []
    for i, row in enumerate(data_rows, start=2 if has_header else 1):
        if len(row) < 2 or not any(row):
            continue
        artist, album = row[0].strip(), row[1].strip()
        if artist and album:
            entries.append({"artist": artist, "album": album})
        else:
            print(f"  [skip] Line {i}: missing artist or album — {row}", file=sys.stderr)
    return entries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cross-reference wishlist with Last.fm stats.")
    parser.add_argument("wishlist", help="Path to wishlist CSV (artist, album)")
    parser.add_argument("--out", default="wishlist_enriched.csv", help="Output CSV path")
    args = parser.parse_args()

    if LASTFM_API_KEY == "YOUR_API_KEY_HERE":
        sys.exit(
            "⚠  Please set your Last.fm API key.\n"
            "   Get one free at: https://www.last.fm/api/account/create\n"
            "   Then replace YOUR_API_KEY_HERE in this script."
        )

    entries = read_wishlist(args.wishlist)
    print(f"Loaded {len(entries)} wishlist entries from '{args.wishlist}'")
    print(f"Fetching Last.fm stats for user '{LASTFM_USERNAME}'...\n")

    results = []
    for i, entry in enumerate(entries, 1):
        artist, album = entry["artist"], entry["album"]
        print(f"  [{i}/{len(entries)}] {artist} — {album}")

        artist_stats = get_artist_stats(artist)
        time.sleep(0.25)  # be polite to the API
        album_stats  = get_album_stats(artist, album)
        time.sleep(0.25)

        # Merge statuses
        if artist_stats["status"] != "ok":
            status = artist_stats["status"]
        elif album_stats["status"] != "ok":
            status = album_stats["status"]
        else:
            status = "ok"

        results.append({
            "artist":                   artist,
            "album":                    album,
            "lastfm_artist_playcount":  artist_stats.get("artist_playcount", ""),
            "lastfm_album_playcount":   album_stats.get("album_playcount", ""),
            "lastfm_album_url":         album_stats.get("album_url", ""),
            "lastfm_artist_url":        artist_stats.get("artist_url", ""),
            "lastfm_album_tracks":      album_stats.get("album_tracks", ""),
            "lastfm_status":            status,
        })

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    ok    = sum(1 for r in results if r["lastfm_status"] == "ok")
    found = sum(1 for r in results if "not_found" not in r["lastfm_status"])
    print(f"\n✓ Done — {ok}/{len(results)} fully matched, output saved to '{args.out}'")


if __name__ == "__main__":
    main()