#!/usr/bin/env python3
"""
ipod_lastfm_picker.py

Pulls your Last.fm "top albums" across every time range (7 day, 1 month,
3 month, 6 month, 12 month, overall), ranks them (favoring things you're
into *right now* without ignoring all-time favorites), filters out albums
you've flagged as blacklisted, and walks you through an interactive
session to build a ~150-track queue for your iPod for the week.

FIRST-TIME SETUP
-----------------
1. pip install requests
2. Get a free Last.fm API key: https://www.last.fm/api/account/create
3. Copy config.example.json to config.json and fill in your api_key,
   username, and (optionally) your local music library path.
4. Run: python3 ipod_lastfm_picker.py

FILES
-----
config.json     - your API key/username/settings (create from example below)
blacklist.json  - auto-created/updated. Categories:
                    - recently_played : you just listened to it, skip for now.
                                        Auto-expires and drops off the blacklist
                                        after 30 days (see RECENTLY_PLAYED_EXPIRY_DAYS).
                    - vinyl           : you own it on vinyl, don't need it digitally
                    - overplayed      : you listen to it too much already
                    - not_downloaded  : you don't have the files for it yet
queue_output.txt/.m3u - the final list this run produces

Everything you reject in the interactive session is saved back into
blacklist.json immediately, so future runs remember your choices.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SECONDS_PER_DAY = 86400
RECENTLY_PLAYED_EXPIRY_DAYS = 30  # auto-remove "recently played" entries after this long

API_ROOT = "https://ws.audioscrobbler.com/2.0/"

# Last.fm periods, paired with a weight that favors recent listening
# without completely ignoring your all-time favorites.
PERIODS = {
    "overall": 1.0,
    "12month": 1.2,
    "6month": 1.4,
    "3month": 1.6,
    "1month": 1.8,
    "7day": 2.2,
}

CONFIG_PATH = Path("config.json")
BLACKLIST_PATH = Path("blacklist.json")

DEFAULT_CONFIG = {
    "api_key": "YOUR_LASTFM_API_KEY",
    "username": "YOUR_LASTFM_USERNAME",
    "target_track_count": 150,
    "default_tracks_per_album_if_unknown": 10,
    "albums_per_period": 100,
    # Optional: point this at your music library so the script can
    # auto-detect "not downloaded" instead of you having to list every
    # album by hand. Expects roughly Artist/Album folder structure.
    # Leave as "" to skip auto-detection and rely only on blacklist.json.
    "music_library_path": "",
}

DEFAULT_BLACKLIST = {
    "recently_played": [],
    "vinyl": [],
    "overplayed": [],
    "not_downloaded": [],
}


# --------------------------------------------------------------------------
# Config / blacklist I/O
# --------------------------------------------------------------------------

def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"Created {CONFIG_PATH} - fill in your api_key and username, then re-run.")
        sys.exit(1)
    cfg = json.loads(CONFIG_PATH.read_text())
    if cfg.get("api_key") in ("", "YOUR_LASTFM_API_KEY", None):
        print(f"Please set your api_key and username in {CONFIG_PATH}")
        sys.exit(1)
    return cfg


def load_blacklist():
    if not BLACKLIST_PATH.exists():
        BLACKLIST_PATH.write_text(json.dumps(DEFAULT_BLACKLIST, indent=2))
    bl = json.loads(BLACKLIST_PATH.read_text())
    for key in DEFAULT_BLACKLIST:
        bl.setdefault(key, [])

    # "recently_played" entries are timestamped and expire automatically.
    # Migrate any old-format plain-string entries to timestamped ones
    # (treated as added "now", so they still get a full window before expiry).
    migrated = []
    for entry in bl.get("recently_played", []):
        if isinstance(entry, dict):
            migrated.append(entry)
        else:
            migrated.append({"key": entry, "added": time.time()})
    bl["recently_played"] = migrated

    changed = purge_expired_recently_played(bl)
    if changed:
        save_blacklist(bl)

    return bl


def purge_expired_recently_played(bl):
    """Drop recently_played entries older than RECENTLY_PLAYED_EXPIRY_DAYS.
    Returns True if anything was removed."""
    cutoff = time.time() - (RECENTLY_PLAYED_EXPIRY_DAYS * SECONDS_PER_DAY)
    before = bl.get("recently_played", [])
    after = [e for e in before if e.get("added", 0) >= cutoff]
    if len(after) != len(before):
        bl["recently_played"] = after
        return True
    return False


def save_blacklist(bl):
    BLACKLIST_PATH.write_text(json.dumps(bl, indent=2, sort_keys=True))


def key_for(artist, album):
    return f"{artist.strip().lower()}::{album.strip().lower()}"


def add_to_blacklist(bl, category, artist, album):
    k = key_for(artist, album)
    if category == "recently_played":
        bl[category].append({"key": k, "added": time.time()})
    else:
        if k not in bl[category]:
            bl[category].append(k)
    save_blacklist(bl)


def blacklisted_category(bl, artist, album):
    k = key_for(artist, album)
    for category, entries in bl.items():
        if category == "recently_played":
            if any(e.get("key") == k for e in entries):
                return category
        else:
            if k in entries:
                return category
    return None


# --------------------------------------------------------------------------
# Last.fm API
# --------------------------------------------------------------------------

def api_call(params, retries=3):
    query = urllib.parse.urlencode(params)
    url = f"{API_ROOT}?{query}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! API call failed ({params.get('method')}): {e}")
                return {}
            time.sleep(1.5 * (attempt + 1))
    return {}


def fetch_top_albums(cfg, period):
    params = {
        "method": "user.gettopalbums",
        "user": cfg["username"],
        "api_key": cfg["api_key"],
        "format": "json",
        "period": period,
        "limit": cfg.get("albums_per_period", 100),
    }
    data = api_call(params)
    albums = data.get("topalbums", {}).get("album", [])
    if isinstance(albums, dict):  # Last.fm returns a dict if there's only one
        albums = [albums]
    return albums


def fetch_track_count(cfg, artist, album, cache):
    k = key_for(artist, album)
    if k in cache:
        return cache[k]
    params = {
        "method": "album.getinfo",
        "api_key": cfg["api_key"],
        "artist": artist,
        "album": album,
        "format": "json",
    }
    data = api_call(params)
    tracks = data.get("album", {}).get("tracks", {}).get("track", [])
    if isinstance(tracks, dict):
        count = 1
    elif isinstance(tracks, list):
        count = len(tracks)
    else:
        count = cfg.get("default_tracks_per_album_if_unknown", 10)
    if not count:
        count = cfg.get("default_tracks_per_album_if_unknown", 10)
    cache[k] = count
    return count


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def build_ranked_candidates(cfg):
    """Fetch every period and combine into one weighted-score ranking."""
    scores = {}       # key -> score
    meta = {}         # key -> {"artist", "album", "playcount_overall"}

    for period, weight in PERIODS.items():
        print(f"Fetching top albums for period: {period} ...")
        albums = fetch_top_albums(cfg, period)
        for rank, a in enumerate(albums):
            artist = a.get("artist", {}).get("name", "Unknown Artist")
            album = a.get("name", "Unknown Album")
            playcount = int(a.get("playcount", 0) or 0)
            k = key_for(artist, album)

            # Rank-based contribution: earlier rank = more points, scaled by
            # period weight. This lets a #3 album on "7day" meaningfully
            # compete with a #1 album on "overall".
            list_len = max(len(albums), 1)
            rank_score = (list_len - rank) * weight

            scores[k] = scores.get(k, 0) + rank_score
            if k not in meta or playcount > meta[k].get("playcount_overall", 0):
                meta[k] = {
                    "artist": artist,
                    "album": album,
                    "playcount_overall": playcount,
                }

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"key": k, "score": s, **meta[k]}
        for k, s in ranked
    ]


# --------------------------------------------------------------------------
# Downloaded-library auto-detection (optional)
# --------------------------------------------------------------------------

def is_downloaded_locally(cfg, artist, album):
    lib = cfg.get("music_library_path", "")
    if not lib or not os.path.isdir(lib):
        return None  # unknown, don't auto-judge
    artist_l = artist.strip().lower()
    album_l = album.strip().lower()
    try:
        for entry in os.scandir(lib):
            if entry.is_dir() and entry.name.strip().lower() == artist_l:
                for sub in os.scandir(entry.path):
                    if sub.is_dir() and album_l in sub.name.strip().lower():
                        return True
                return False
    except OSError:
        pass
    return None


# --------------------------------------------------------------------------
# Interactive session
# --------------------------------------------------------------------------

REJECT_MAP = {
    "1": "recently_played",
    "2": "vinyl",
    "3": "overplayed",
    "4": "not_downloaded",
}

HELP_TEXT = """
  [a] accept into this week's queue
  [1] reject: recently played
  [2] reject: I have it on vinyl
  [3] reject: I listen to it too often (overplayed)
  [4] reject: not downloaded
  [s] skip for now (ask again next run, no blacklist entry)
  [q] quit and save queue so far
"""


def run_interactive(cfg, bl, candidates, track_cache):
    target = cfg.get("target_track_count", 150)
    total_tracks = 0
    accepted = []
    idx = 0

    print(HELP_TEXT)

    while idx < len(candidates) and total_tracks < target:
        c = candidates[idx]
        artist, album = c["artist"], c["album"]

        # Skip anything already blacklisted, silently.
        cat = blacklisted_category(bl, artist, album)
        if cat:
            idx += 1
            continue

        # Auto-flag not-downloaded if we can detect it, but still let the
        # user confirm/override interactively rather than silently dropping.
        auto_downloaded = is_downloaded_locally(cfg, artist, album)

        track_count = fetch_track_count(cfg, artist, album, track_cache)
        remaining = target - total_tracks

        note = ""
        if auto_downloaded is False:
            note = "  [not found in local library]"
        elif auto_downloaded is True:
            note = "  [found in local library]"

        print(f"\n({total_tracks}/{target} tracks so far, {remaining} to go)")
        print(f"  {artist} - {album}  ({track_count} tracks, score={c['score']:.0f}){note}")

        choice = input("  > ").strip().lower()

        if choice == "q":
            break
        elif choice == "s":
            idx += 1
            continue
        elif choice in REJECT_MAP:
            category = REJECT_MAP[choice]
            add_to_blacklist(bl, category, artist, album)
            expiry_note = " (expires in 30 days)" if category == "recently_played" else ""
            print(f"  Added to blacklist -> {category}{expiry_note}. Pulling next suggestion...")
            idx += 1
            continue
        elif choice == "a" or choice == "":
            accepted.append({**c, "track_count": track_count})
            total_tracks += track_count
            idx += 1
        else:
            print("  Not a recognized option, try again.")
            continue

    return accepted, total_tracks


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def write_queue(accepted, total_tracks):
    out_txt = Path("queue_output.txt")
    out_m3u = Path("queue_output.m3u")

    lines = [f"Weekly iPod queue - {total_tracks} tracks across {len(accepted)} albums\n"]
    for a in accepted:
        lines.append(f"- {a['artist']} - {a['album']} ({a['track_count']} tracks)")
    out_txt.write_text("\n".join(lines))

    m3u_lines = ["#EXTM3U"]
    for a in accepted:
        m3u_lines.append(f"# {a['artist']} - {a['album']}")
    out_m3u.write_text("\n".join(m3u_lines))

    print(f"\nSaved {out_txt} and {out_m3u}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    cfg = load_config()
    bl = load_blacklist()
    track_cache = {}

    candidates = build_ranked_candidates(cfg)
    print(f"\nFound {len(candidates)} unique candidate albums across all time ranges.\n")

    accepted, total_tracks = run_interactive(cfg, bl, candidates, track_cache)

    if not accepted:
        print("No albums accepted, nothing to save.")
        return

    write_queue(accepted, total_tracks)
    print(f"\nDone. {len(accepted)} albums, ~{total_tracks} tracks queued for the week.")


if __name__ == "__main__":
    main()