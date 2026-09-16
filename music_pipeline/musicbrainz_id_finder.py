"""
musicbrainz_id_tagger.py

Walks a folder of FLAC files, finds every distinct artist (using
ALBUMARTIST, falling back to ARTIST), looks each one up on MusicBrainz,
and writes the resolved MusicBrainz Artist ID into the
MUSICBRAINZ_ARTISTID tag (and MUSICBRAINZ_ALBUMARTISTID, when the
artist is credited as an album artist) on every track by that artist.

Why this exists: artist names like "Confetti" or "Ghost" collide with
other, unrelated acts on MusicBrainz/Last.fm. Once a track is tagged
with the correct MBID, lookups by ID are unambiguous -- no more guessing
which "Confetti" you meant. This script is meant to be run BEFORE
lastfm_genre_tagger.py, which will prefer the MBID tag when present.

Disambiguation:
    If MusicBrainz returns one clearly-best match, it's used
    automatically. If there are multiple plausible matches (a common
    problem for short/generic band names), the script lists each
    candidate with its disambiguation comment, country, type, active
    years, and a few of their best-known recordings -- pulled live from
    MusicBrainz -- so you can recognize which one is actually in your
    library. You then pick a number, or skip.

Requirements:
    pip install mutagen requests tqdm

Usage:
    python musicbrainz_id_tagger.py /path/to/music/folder --contact "you@example.com"

    # Preview without writing anything:
    python musicbrainz_id_tagger.py /path/to/music/folder --contact "you@example.com" --dry-run

    # Re-check artists that already have an MBID tag:
    python musicbrainz_id_tagger.py /path/to/music/folder --contact "you@example.com" --force

Why --contact is required:
    MusicBrainz requires every API client to send a descriptive
    User-Agent string containing real contact info, so they can reach
    you if your script misbehaves. Pass an email address or a URL --
    anything that identifies you. This is MusicBrainz's policy, not
    something this script invented.
    See: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
"""

import argparse
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from mutagen.flac import FLAC
from tqdm import tqdm

MB_API_URL = "https://musicbrainz.org/ws/2"

# MusicBrainz requires >=1 second between requests per IP. Keep a small
# safety margin above that.
MB_MIN_DELAY = 1.1


def find_flac_files(root: Path):
    """Recursively yield all .flac files under root."""
    yield from root.rglob("*.flac")


def get_artist_name(audio: FLAC):
    """
    Return the artist name to use for MusicBrainz lookup: prefers
    ALBUMARTIST, falls back to ARTIST. Returns None if neither is set.
    """
    artist = audio.get("albumartist", [None])[0]
    if not artist:
        artist = audio.get("artist", [None])[0]
    return artist.strip() if artist else None


def has_artist_mbid(audio: FLAC):
    """Return True if this file already has a MUSICBRAINZ_ARTISTID tag."""
    return bool(audio.get("musicbrainz_artistid", [None])[0])


def scan_artists(root: Path, force: bool):
    """
    Scan all FLAC files under root and group their paths by artist name.
    Returns a dict: {artist_name: [Path, Path, ...]}

    Files with no artist tag are skipped. Unless force=True, files that
    already carry a MUSICBRAINZ_ARTISTID tag are excluded from the
    results (their artist name is still skipped as a whole only if ALL
    of that artist's files already have an MBID; otherwise the
    not-yet-tagged files are still included).
    """
    artists = {}
    skipped = []

    for flac_path in find_flac_files(root):
        try:
            audio = FLAC(flac_path)
        except Exception as e:
            tqdm.write(f"  [WARN] Could not read {flac_path}: {e}")
            skipped.append(flac_path)
            continue

        name = get_artist_name(audio)
        if not name:
            tqdm.write(f"  [WARN] No ARTIST/ALBUMARTIST tag, skipping: {flac_path}")
            skipped.append(flac_path)
            continue

        if not force and has_artist_mbid(audio):
            continue

        artists.setdefault(name, []).append(flac_path)

    return artists, skipped


def mb_request(session: requests.Session, path: str, params: dict, last_request_time: list):
    """
    Make a rate-limited GET request to the MusicBrainz API.
    last_request_time is a 1-element list used as a mutable timestamp
    holder so callers can share rate-limit state across calls.
    """
    elapsed = time.time() - last_request_time[0]
    if elapsed < MB_MIN_DELAY:
        time.sleep(MB_MIN_DELAY - elapsed)

    params = dict(params)
    params["fmt"] = "json"

    try:
        resp = session.get(f"{MB_API_URL}/{path}", params=params, timeout=20)
        last_request_time[0] = time.time()
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        last_request_time[0] = time.time()
        tqdm.write(f"    [ERROR] MusicBrainz request failed: {e}")
        return None
    except ValueError:
        tqdm.write("    [ERROR] Bad JSON from MusicBrainz")
        return None


def search_artist_candidates(session, artist_name: str, last_request_time: list, limit: int = 8):
    """
    Search MusicBrainz for artists matching artist_name.
    Returns a list of candidate dicts (raw MusicBrainz artist objects),
    sorted by MusicBrainz's relevance score (highest first), or an
    empty list on failure / no results.
    """
    data = mb_request(
        session,
        "artist",
        {"query": f'artist:"{artist_name}"', "limit": limit},
        last_request_time,
    )
    if not data:
        return []

    candidates = data.get("artists", [])
    candidates.sort(key=lambda a: int(a.get("score", 0)), reverse=True)
    return candidates


def fetch_top_recordings(session, artist_mbid: str, last_request_time: list, limit: int = 5):
    """
    Fetch a handful of recording titles credited to this artist MBID,
    to help the user recognize the artist. Best-effort: returns an
    empty list on any failure.
    """
    data = mb_request(
        session,
        "recording",
        {"artist": artist_mbid, "limit": limit},
        last_request_time,
    )
    if not data:
        return []

    recordings = data.get("recordings", [])
    titles = []
    for r in recordings:
        title = r.get("title")
        if title and title not in titles:
            titles.append(title)
    return titles


def describe_candidate(candidate: dict):
    """Build a one-line human-readable summary of a MusicBrainz artist candidate."""
    name = candidate.get("name", "Unknown")
    a_type = candidate.get("type", "")
    country = candidate.get("country", "")
    disambig = candidate.get("disambiguation", "")
    life_span = candidate.get("life-span", {}) or {}
    begin = life_span.get("begin", "")
    end = life_span.get("end", "")
    score = candidate.get("score", "?")

    years = ""
    if begin or end:
        years = f"{begin or '?'}\u2013{end or 'present'}"

    bits = [b for b in [a_type, country, years] if b]
    meta = f" ({', '.join(bits)})" if bits else ""
    disambig_str = f" -- {disambig}" if disambig else ""

    return f"{name}{meta}{disambig_str}  [match score: {score}]"


def prompt_artist_choice(artist_name: str, candidates: list, session, last_request_time: list):
    """
    Show the user a list of candidate artists (with sample recordings
    to aid recognition) and ask them to pick one, skip, or open a
    MusicBrainz search link in their browser.

    Returns a chosen candidate dict, or None if skipped.
    """
    tqdm.write(f"\n    Multiple possible MusicBrainz matches for artist '{artist_name}':")

    for i, c in enumerate(candidates, start=1):
        tqdm.write(f"      [{i}] {describe_candidate(c)}")
        mbid = c.get("id")
        if mbid:
            titles = fetch_top_recordings(session, mbid, last_request_time)
            if titles:
                tqdm.write(f"          Known tracks: {', '.join(titles)}")
            tqdm.write(f"          https://musicbrainz.org/artist/{mbid}")

    search_url = (
        "https://musicbrainz.org/search?query="
        f"{urllib.parse.quote_plus(artist_name)}&type=artist&method=indexed"
    )
    tqdm.write(f"    Full search on MusicBrainz: {search_url}")

    while True:
        choice = input(
            f"    Pick a number [1-{len(candidates)}], or [s]kip this artist: "
        ).strip().lower()

        if choice in ("s", "skip", ""):
            return None

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]

        tqdm.write(f"    Please enter a number from 1 to {len(candidates)}, or 's'.")


def resolve_artist_mbid(artist_name: str, session, last_request_time: list, interactive: bool,
                         auto_threshold: int = 95):
    """
    Resolve a single MusicBrainz Artist ID for the given artist name.

    - If MusicBrainz returns no candidates: return None.
    - If exactly one candidate, or the top candidate's score is >=
      auto_threshold and clearly ahead of the next one: auto-accept it.
    - Otherwise (genuinely ambiguous): prompt the user, if interactive.

    Returns (mbid, resolved_name) or (None, None) if unresolved/skipped.
    """
    candidates = search_artist_candidates(session, artist_name, last_request_time)
    if not candidates:
        tqdm.write(f"    No MusicBrainz results for '{artist_name}'.")
        return None, None

    top = candidates[0]
    top_score = int(top.get("score", 0))

    # Unambiguous case: only one result, or a dominant top match.
    if len(candidates) == 1 or (
        top_score >= auto_threshold
        and (len(candidates) < 2 or top_score - int(candidates[1].get("score", 0)) >= 10)
    ):
        tqdm.write(f"    Matched '{artist_name}' -> '{top.get('name')}' "
                   f"({describe_candidate(top)})")
        return top.get("id"), top.get("name")

    if not interactive:
        tqdm.write(f"    Ambiguous match for '{artist_name}' ({len(candidates)} candidates); "
                   f"skipping (use without --no-prompt to choose interactively).")
        return None, None

    chosen = prompt_artist_choice(artist_name, candidates, session, last_request_time)
    if chosen is None:
        return None, None
    return chosen.get("id"), chosen.get("name")


def apply_mbid_tags(flac_path: Path, artist_mbid: str, audio_albumartist_matches: bool, dry_run: bool):
    """
    Write MUSICBRAINZ_ARTISTID (always) and MUSICBRAINZ_ALBUMARTISTID
    (only if this file's ALBUMARTIST is the artist we resolved) to a
    single FLAC file.
    """
    audio = FLAC(flac_path)

    audio["musicbrainz_artistid"] = [artist_mbid]
    if audio_albumartist_matches:
        audio["musicbrainz_albumartistid"] = [artist_mbid]

    if dry_run:
        return
    audio.save()


def main():
    parser = argparse.ArgumentParser(
        description="Resolve and tag MusicBrainz Artist IDs on FLAC files."
    )
    parser.add_argument("folder", type=str, help="Folder containing FLAC files (searched recursively)")
    parser.add_argument(
        "--contact", type=str, required=True,
        help="Your email or a URL, used in the required MusicBrainz User-Agent string."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-resolve artists that already have a MUSICBRAINZ_ARTISTID tag."
    )
    parser.add_argument(
        "--no-prompt", action="store_true",
        help="Never pause for ambiguous matches; skip them instead (use for unattended runs)."
    )
    parser.add_argument(
        "--auto-threshold", type=int, default=95,
        help="MusicBrainz match score (0-100) at/above which a dominant top result is "
             "auto-accepted without prompting. Default: 95."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without writing any tags to disk."
    )
    parser.add_argument(
        "--log-file", type=str, default=None,
        help="Path to write a list of artists that were skipped/unresolved, for later review."
    )

    args = parser.parse_args()
    root = Path(args.folder).expanduser().resolve()

    if not root.is_dir():
        tqdm.write(f"Error: '{root}' is not a valid directory.")
        sys.exit(1)

    session = requests.Session()
    session.headers["User-Agent"] = f"FlacMBIDTagger/1.0 ( {args.contact} )"
    last_request_time = [0.0]

    tqdm.write(f"Scanning '{root}' for FLAC files...")
    artists, skipped = scan_artists(root, force=args.force)

    if not artists:
        tqdm.write("No artists needing MBID lookup were found. Nothing to do.")
        sys.exit(0)

    tqdm.write(f"\nFound {len(artists)} distinct artist(s) across "
               f"{sum(len(v) for v in artists.values())} track(s).")
    if skipped:
        tqdm.write(f"({len(skipped)} file(s) skipped due to missing/unreadable tags.)")

    if args.dry_run:
        tqdm.write("\n--- DRY RUN: no files will be modified ---")

    unresolved = []
    progress = tqdm(sorted(artists.items()), desc="Artists", unit="artist")

    for artist_name, files in progress:
        progress.set_postfix_str(artist_name[:40])
        tqdm.write(f"\n'{artist_name}'  ({len(files)} track(s))")

        mbid, resolved_name = resolve_artist_mbid(
            artist_name, session, last_request_time,
            interactive=not args.no_prompt,
            auto_threshold=args.auto_threshold,
        )

        if not mbid:
            unresolved.append(artist_name)
            continue

        for f in tqdm(files, desc="  Tracks", unit="file", leave=False):
            try:
                audio = FLAC(f)
                album_artist = audio.get("albumartist", [None])[0]
                matches_album_artist = (
                    album_artist is not None and album_artist.strip() == artist_name
                )
                apply_mbid_tags(f, mbid, matches_album_artist, dry_run=args.dry_run)
                action = "Would set" if args.dry_run else "Set"
                tqdm.write(f"      {action} MBID on: {f.name}")
            except Exception as e:
                tqdm.write(f"      [ERROR] Failed to write tag to {f}: {e}")

    if unresolved:
        tqdm.write(f"\n{len(unresolved)} artist(s) left unresolved:")
        for name in unresolved:
            tqdm.write(f"  - {name}")

        if args.log_file:
            log_path = Path(args.log_file).expanduser()
            try:
                with log_path.open("w", encoding="utf-8") as f:
                    f.write("Artists left unresolved (no MusicBrainz MBID tagged)\n")
                    f.write("=" * 60 + "\n\n")
                    for name in unresolved:
                        search_url = (
                            "https://musicbrainz.org/search?query="
                            f"{urllib.parse.quote_plus(name)}&type=artist&method=indexed"
                        )
                        f.write(f"{name}\n  {search_url}\n\n")
                tqdm.write(f"\nWrote unresolved-artist list to: {log_path}")
            except OSError as e:
                tqdm.write(f"[ERROR] Could not write log file {log_path}: {e}")

    tqdm.write("\nDone." if not args.dry_run else "\nDry run complete. Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()