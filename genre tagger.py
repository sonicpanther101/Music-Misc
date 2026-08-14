"""
lastfm_genre_tagger.py

Walks a folder of properly-tagged FLAC files, groups tracks into albums
using their existing ALBUMARTIST/ARTIST + ALBUM tags, looks up each
album's top tags on Last.fm, and rewrites the GENRE tag on every track
in that album as a single ';'-separated string of tags
(e.g. "Rock;Indie;80s").

The original GENRE tag is fully replaced, not appended to.

Tip: run musicbrainz_id_tagger.py on your library first. If a track has
a MUSICBRAINZ_ARTISTID / MUSICBRAINZ_ALBUMARTISTID tag, this script
will use it to query Last.fm unambiguously by ID, avoiding name
collisions (e.g. a generic band name like "Confetti" matching a
completely different, unrelated act on Last.fm).

Tag resolution order per album:
    0. If an MBID tag is present: artist.getTopTags by MusicBrainz
       Artist ID -- unambiguous, but artist-level rather than
       album-specific
    1. Last.fm album.getTopTags for (artist, album)
    2. Fallback: Last.fm track.getTopTags, tried against the album title
       itself, then against every distinct TITLE found among its files.
       This covers singles that aren't registered as "albums" on
       Last.fm, and cases where the track name differs slightly from
       the album name (e.g. a remix credit in one but not the other)
    3. If all of that fails and prompting is enabled (default): show a
       Last.fm search link for the artist/album and pause to ask
       whether to retry, enter tags manually, or skip that album

A built-in + optional user-supplied denylist filters out common junk
tags (e.g. "seen live", "favorite", "cd").

API KEY STORAGE:
    Instead of passing your Last.fm API key on the command line (where
    it can end up in shell history, process lists, etc.), this script
    stores it encrypted on disk and asks you for a password to decrypt
    it each time you run it.

    First-time setup:
        python lastfm_genre_tagger.py --set-api-key

    This will ask for your Last.fm API key and a password to encrypt it
    with, then save the encrypted key to (by default):
        ~/.lastfm_genre_tagger/api_key.enc

    Every subsequent run just asks for that password:
        python lastfm_genre_tagger.py /path/to/music/folder

    The password is never stored anywhere -- only the encrypted API key
    is. If you forget the password, just run --set-api-key again to
    overwrite it with a new key/password pair.

Requirements:
    pip install mutagen requests tqdm cryptography

Usage:
    # One-time: store your API key, encrypted with a password of your choosing
    python lastfm_genre_tagger.py --set-api-key

    # Normal run (uses sensible defaults for everything else; asks for
    # your password once to unlock the stored API key)
    python lastfm_genre_tagger.py /path/to/music/folder

    # Run in the current directory (folder is optional, defaults to ".")
    python lastfm_genre_tagger.py

    # Preview changes without writing anything:
    python lastfm_genre_tagger.py /path/to/music/folder --dry-run

    # Add your own denylist entries on top of the built-in ones:
    python lastfm_genre_tagger.py /path/to/music/folder --denylist-file my_denylist.txt

    # Never pause for manual input; just skip albums with no tags found:
    python lastfm_genre_tagger.py /path/to/music/folder --no-prompt

    # Use a non-default location for the encrypted key file:
    python lastfm_genre_tagger.py /path/to/music/folder --key-file /path/to/key.enc

How to get a free Last.fm API key:
    1. Go to https://www.last.fm/api/account/create
    2. Log in / create a Last.fm account if you don't have one.
    3. Fill in the "Application name" field (anything, e.g. "MyTagger").
       Other fields can be left blank.
    4. Submit the form. Your API key ("API Key") will be shown on the
       resulting page and in your account's API page:
       https://www.last.fm/api/accounts
    5. You only need the API Key (not the "Shared secret") for this
       script, since it only reads public tag data.
"""

import argparse
import base64
import getpass
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from mutagen.flac import FLAC
from tqdm import tqdm

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

# Where the encrypted API key lives by default. Overridable with --key-file.
DEFAULT_KEY_FILE = Path.home() / ".lastfm_genre_tagger" / "api_key.enc"

# Default location for the skipped-albums log, written automatically at
# the end of a run if any albums were skipped (override with --log-file,
# or disable with --no-log).
DEFAULT_LOG_FILE = "skipped_albums.log"

# PBKDF2 iteration count for deriving the encryption key from the password.
PBKDF2_ITERATIONS = 480_000

# Tags that are noise on Last.fm: personal labels ("seen live", own username),
# meta/list tags, decade/year tags that aren't really genres, etc.
# Comparison is case-insensitive. Edit this set to taste.
DEFAULT_DENYLIST = {
    "seen live",
    "favorite",
    "favorites",
    "favourite",
    "favourites",
    "awesome",
    "good",
    "great",
    "love",
    "love song",
    "love songs",
    "amazing",
    "best",
    "best ever",
    "beautiful",
    "cool",
    "epic",
    "perfect",
    "favorite songs",
    "favourite songs",
    "albums i own",
    "in my collection",
    "owned",
    "cd",
    "vinyl",
    "mp3",
    "spotify",
    "checkthissong",
    "check out this song",
    "under 2000 listeners",
    "to listen",
    "to check out",
    "all",
    "misc",
    "other",
    "unknown",
    "none",
    "n/a",
    "wsum 91.7 fm madison",
    "to get",
}


# --------------------------------------------------------------------------
# Encrypted API key handling
# --------------------------------------------------------------------------

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a password + salt via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def save_encrypted_api_key(api_key: str, password: str, path: Path):
    """Encrypt api_key with password and write it (plus a fresh salt) to path."""
    salt = os.urandom(16)
    fernet_key = _derive_fernet_key(password, salt)
    token = Fernet(fernet_key).encrypt(api_key.encode("utf-8"))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(salt + b"\n" + token)

    try:
        os.chmod(path, 0o600)  # best-effort: owner read/write only
    except OSError:
        pass


def load_encrypted_api_key(password: str, path: Path) -> str:
    """Decrypt and return the API key stored at path, using password."""
    with path.open("rb") as f:
        data = f.read()

    try:
        salt, token = data.split(b"\n", 1)
    except ValueError:
        raise ValueError(f"Key file {path} is malformed. Re-run with --set-api-key.")

    fernet_key = _derive_fernet_key(password, salt)
    try:
        return Fernet(fernet_key).decrypt(token).decode("utf-8")
    except InvalidToken:
        raise ValueError("Incorrect password, or the key file is corrupted.")


def setup_api_key(path: Path):
    """Interactively prompt for a Last.fm API key + password and store it."""
    tqdm.write("Setting up your Last.fm API key.")
    tqdm.write(
        "Don't have one? Create one free at https://www.last.fm/api/account/create"
    )
    api_key = getpass.getpass("Last.fm API key (input hidden): ").strip()
    if not api_key:
        tqdm.write("No API key entered, aborting.")
        sys.exit(1)

    while True:
        password = getpass.getpass("Choose a password to encrypt it with: ")
        confirm = getpass.getpass("Confirm password: ")
        if not password:
            tqdm.write("Password can't be empty, try again.")
            continue
        if password != confirm:
            tqdm.write("Passwords didn't match, try again.")
            continue
        break

    save_encrypted_api_key(api_key, password, path)
    tqdm.write(f"Encrypted API key saved to: {path}")
    tqdm.write("You'll be asked for this password each time you run the script.")


def unlock_api_key(path: Path) -> str:
    """Prompt for the password and decrypt the stored API key, with retries."""
    if not path.is_file():
        tqdm.write(f"No encrypted API key found at: {path}")
        tqdm.write("Run this first:  python lastfm_genre_tagger.py --set-api-key")
        sys.exit(1)

    for attempt in range(3):
        password = getpass.getpass("Password to unlock your Last.fm API key: ")
        try:
            return load_encrypted_api_key(password, path)
        except ValueError as e:
            tqdm.write(f"[ERROR] {e}")
            if attempt < 2:
                tqdm.write("Try again.")

    tqdm.write("Too many failed attempts, exiting.")
    sys.exit(1)


# --------------------------------------------------------------------------
# Denylist
# --------------------------------------------------------------------------

def load_denylist(path: Optional[str]):
    """
    Build the final denylist (lowercased) from DEFAULT_DENYLIST plus any
    extra entries in a user-supplied text file (one tag per line, '#'
    starts a comment, blank lines ignored).
    """
    denylist = {t.lower() for t in DEFAULT_DENYLIST}

    if path:
        p = Path(path).expanduser()
        if not p.is_file():
            tqdm.write(f"[WARN] Denylist file not found: {p} (continuing with built-in denylist only)")
            return denylist
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                denylist.add(line.lower())

    return denylist


def find_flac_files(root: Path):
    """Recursively yield all .flac files under root."""
    yield from root.rglob("*.flac")


def get_track_title(audio: FLAC):
    """Return the TITLE tag of a FLAC file, or None if missing."""
    title = audio.get("title", [None])[0]
    return title.strip() if title else None


def get_artist_mbid(audio: FLAC):
    """
    Return the MusicBrainz Artist ID for a FLAC file, if present.
    Prefers MUSICBRAINZ_ALBUMARTISTID, falls back to MUSICBRAINZ_ARTISTID.
    These are written by musicbrainz_id_tagger.py.
    """
    mbid = audio.get("musicbrainz_albumartistid", [None])[0]
    if not mbid:
        mbid = audio.get("musicbrainz_artistid", [None])[0]
    return mbid.strip() if mbid else None


def get_album_key(audio: FLAC):
    """
    Build a grouping key from a FLAC file's tags.
    Prefers ALBUMARTIST, falls back to ARTIST, paired with ALBUM.
    Returns (album_artist, album_title) or None if ALBUM tag is missing.
    """
    album = audio.get("album", [None])[0]
    if not album:
        return None

    artist = audio.get("albumartist", [None])[0]
    if not artist:
        artist = audio.get("artist", [None])[0]
    if not artist:
        artist = "Unknown Artist"

    return (artist.strip(), album.strip())


def scan_albums(root: Path):
    """
    Scan all FLAC files under root and group their file paths by
    (album_artist, album_title). Returns a dict:
        {(artist, album): [Path, Path, ...]}
    Files without an ALBUM tag are skipped and reported.
    """
    albums = {}
    skipped = []

    for flac_path in find_flac_files(root):
        try:
            audio = FLAC(flac_path)
        except Exception as e:
            tqdm.write(f"  [WARN] Could not read {flac_path}: {e}")
            skipped.append(flac_path)
            continue

        key = get_album_key(audio)
        if key is None:
            tqdm.write(f"  [WARN] No ALBUM tag, skipping: {flac_path}")
            skipped.append(flac_path)
            continue

        albums.setdefault(key, []).append(flac_path)

    return albums, skipped


def fetch_lastfm_artist_tags_by_mbid(api_key: str, artist_mbid: str, min_weight: int = 0, denylist: Optional[set] = None):
    """
    Query Last.fm's artist.getTopTags using a MusicBrainz Artist ID
    instead of an artist name string. This sidesteps name-collision
    problems entirely (e.g. a generic band name matching an unrelated
    act on Last.fm), since the MBID is unambiguous.

    Requires the MBID to have been written by musicbrainz_id_tagger.py
    (or similar) into MUSICBRAINZ_ARTISTID / MUSICBRAINZ_ALBUMARTISTID.
    """
    params = {
        "method": "artist.gettoptags",
        "mbid": artist_mbid,
        "api_key": api_key,
        "format": "json",
    }

    return _query_lastfm_tags(params, f"mbid:{artist_mbid} (artist)", min_weight, denylist)


def fetch_lastfm_tags(api_key: str, artist: str, album: str, min_weight: int = 0, denylist: Optional[set] = None):
    """
    Query Last.fm's album.getTopTags for the given artist/album.
    Returns a list of tag names in order of weight (highest first),
    or an empty list if none were found / on error.

    min_weight: ignore tags whose Last.fm 'weight' (relative popularity,
    0-100) is below this. Use 0 to keep everything Last.fm returns.
    denylist: set of lowercased tag names to exclude entirely.
    """
    params = {
        "method": "album.gettoptags",
        "artist": artist,
        "album": album,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
    }

    return _query_lastfm_tags(params, f"{artist} - {album}", min_weight, denylist)


def fetch_lastfm_track_tags(api_key: str, artist: str, track: str, min_weight: int = 0, denylist: Optional[set] = None):
    """
    Query Last.fm's track.getTopTags for a given artist/track.
    Used as a fallback when album-level tags aren't available (e.g. for
    singles, or albums whose title doesn't exactly match Last.fm's record).
    """
    params = {
        "method": "track.gettoptags",
        "artist": artist,
        "track": track,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
    }

    return _query_lastfm_tags(params, f"{artist} - {track} (track)", min_weight, denylist)


def _query_lastfm_tags(params: dict, label: str, min_weight: int, denylist: Optional[set]):
    """Shared request/parse/filter logic for album and track tag lookups."""
    try:
        resp = requests.get(LASTFM_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        tqdm.write(f"    [ERROR] Last.fm request failed for '{label}': {e}")
        return []
    except ValueError:
        tqdm.write(f"    [ERROR] Bad JSON from Last.fm for '{label}'")
        return []

    if "error" in data:
        tqdm.write(f"    [ERROR] Last.fm API error for '{label}': {data.get('message')}")
        return []

    toptags = data.get("toptags", {})
    tag_list = toptags.get("tag", [])

    # Surface what Last.fm actually resolved the artist/album/track to.
    # Useful for diagnosing namesake collisions (e.g. a generic band name
    # like "Confetti" matching a different, unrelated act on Last.fm).
    resolved_artist = toptags.get("@attr", {}).get("artist") or toptags.get("artist")
    requested_artist = params.get("artist")
    if resolved_artist and requested_artist and resolved_artist.lower() != requested_artist.lower():
        tqdm.write(f"    [NOTE] Last.fm resolved artist '{requested_artist}' -> '{resolved_artist}' for '{label}'")

    # Last.fm returns a dict (not a list) when there's exactly one tag
    if isinstance(tag_list, dict):
        tag_list = [tag_list]

    denylist = denylist or set()
    tags = []
    for t in tag_list:
        try:
            weight = int(t.get("count", 0))
        except (TypeError, ValueError):
            weight = 0
        if weight < min_weight:
            continue
        name = t.get("name", "").strip()
        if not name:
            continue
        if name.lower() in denylist:
            continue
        tags.append(name)

    return tags


def build_lastfm_search_url(artist: str, query: str):
    """Build a Last.fm search URL for the given artist + track/album text."""
    q = urllib.parse.quote_plus(f"{artist} {query}")
    return f"https://www.last.fm/search?q={q}"


def prompt_manual_tags(search_url: Optional[str] = None):
    """
    Pause and ask the user what to do when no tags could be found
    automatically. Returns a list of tag strings (possibly empty).
    """
    tqdm.write("    No Last.fm tags found automatically.")
    if search_url:
        tqdm.write(f"    Search Last.fm manually: {search_url}")
    while True:
        choice = input(
            "    [r]etry lookup / [m]anually enter tags / [s]kip this album? [r/m/s]: "
        ).strip().lower()

        if choice in ("s", "skip", ""):
            return None  # signal: leave genre untouched

        if choice in ("r", "retry"):
            return "RETRY"

        if choice in ("m", "manual"):
            raw = input("    Enter tags separated by ';' (e.g. Rock;Blues Rock;Icelandic): ").strip()
            if not raw:
                tqdm.write("    Nothing entered, skipping album.")
                return None
            return [t.strip() for t in raw.split(";") if t.strip()]

        tqdm.write("    Please enter 'r', 'm', or 's'.")


def resolve_album_tags(api_key, artist, album, files, min_weight, denylist, delay, interactive):
    """
    Try to get a list of genre tags for an album, in this order:
      0. If any file in the album has a MUSICBRAINZ_ARTISTID /
         MUSICBRAINZ_ALBUMARTISTID tag (written by
         musicbrainz_id_tagger.py), use artist.getTopTags with that
         MBID. This is unambiguous -- it sidesteps name collisions like
         "Confetti" matching the wrong band entirely. These are
         artist-level tags, not album-specific, but they're a great,
         risk-free first guess.
      1. album.getTopTags for (artist, album)
      2. track.getTopTags for the album title itself, treated as a track
         name. This covers singles where Last.fm's "track" page exists
         under a name like "Way Less Sad - Cash Cash Remix" but our
         ALBUM tag is the bare "Way Less Sad (Cash Cash Remix)" -- and
         also the reverse case.
      3. track.getTopTags for each distinct TITLE tag found among the
         album's files (in case the album title and the track title
         differ, e.g. a single named after its A-side).
      4. If interactive and still nothing: show a Last.fm search link
         and prompt the user to retry, enter tags manually, or skip.

    Returns a list of tags, or None if the album should be left untouched.
    """
    # Step 0: MBID-based artist lookup, if available.
    artist_mbid = None
    for f in files:
        try:
            audio = FLAC(f)
        except Exception:
            continue
        artist_mbid = get_artist_mbid(audio)
        if artist_mbid:
            break

    if artist_mbid:
        tags = fetch_lastfm_artist_tags_by_mbid(api_key, artist_mbid, min_weight=min_weight, denylist=denylist)
        if tags:
            tqdm.write(f"    Found tags via MusicBrainz artist ID ({artist_mbid}).")
            return tags
        tqdm.write(f"    No tags via MusicBrainz artist ID ({artist_mbid}); falling back to name-based lookup.")

    while True:
        tags = fetch_lastfm_tags(api_key, artist, album, min_weight=min_weight, denylist=denylist)
        if tags:
            return tags

        # Collect candidate "track name" strings to try as a fallback.
        # Always try the album title itself first (singles are often
        # filed as a track under the same name, sometimes with extra
        # text like a remix credit).
        candidates = [album]

        for f in files:
            try:
                audio = FLAC(f)
            except Exception:
                continue
            title = get_track_title(audio)
            if title and title not in candidates:
                candidates.append(title)

        found_via = None
        for candidate in candidates:
            tqdm.write(f"    No album-level tags. Trying track-level tags for '{candidate}'...")
            tags = fetch_lastfm_track_tags(
                api_key, artist, candidate, min_weight=min_weight, denylist=denylist
            )
            if tags:
                found_via = candidate
                break

        if tags:
            tqdm.write(f"    Found tags via track-level fallback ('{found_via}').")
            return tags

        if not interactive:
            return None

        search_url = build_lastfm_search_url(artist, album)
        result = prompt_manual_tags(search_url=search_url)
        if result == "RETRY":
            time.sleep(delay)
            continue
        return result  # either None (skip) or a list of manual tags


def apply_genre_tag(flac_path: Path, genre_string: str, dry_run: bool):
    """Replace the GENRE tag on a single FLAC file."""
    audio = FLAC(flac_path)

    if "genre" in audio:
        del audio["genre"]

    audio["genre"] = [genre_string]

    if dry_run:
        return
    audio.save()


def main():
    parser = argparse.ArgumentParser(
        description="Replace GENRE tags on FLAC albums using Last.fm's top tags."
    )
    parser.add_argument(
        "folder",
        type=str,
        nargs="?",
        default="",
        help="Folder containing FLAC files, searched recursively (default: current directory)",
    )
    parser.add_argument(
        "--set-api-key",
        action="store_true",
        help="Interactively prompt for your Last.fm API key and a password, "
             "encrypt the key, save it to --key-file, then exit.",
    )
    parser.add_argument(
        "--key-file",
        type=str,
        default=str(DEFAULT_KEY_FILE),
        help=f"Path to the encrypted API key file (default: {DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "--min-weight",
        type=int,
        default=0,
        help="Minimum Last.fm tag weight (0-100) to keep a tag. Default 0 = keep all tags.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Seconds to wait between Last.fm requests, to be polite to the API. Default 0.25",
    )
    parser.add_argument(
        "--denylist-file",
        type=str,
        default=None,
        help="Path to a text file of extra tags to exclude (one per line, '#' for comments). "
             "These are added to the built-in denylist of common junk tags.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Never pause for manual input; just skip albums where no tags could be found. "
             "By default the script pauses and asks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing any tags to disk.",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=DEFAULT_LOG_FILE,
        help="Path to write a list of albums that were skipped (no tags found), with "
             f"a Last.fm search link for each (default: {DEFAULT_LOG_FILE}).",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Don't write a skipped-albums log file, even if some albums were skipped.",
    )

    args = parser.parse_args()

    key_path = Path(args.key_file).expanduser()

    if args.set_api_key:
        setup_api_key(key_path)
        sys.exit(0)

    api_key = unlock_api_key(key_path)

    root = Path(args.folder).expanduser().resolve()

    if not root.is_dir():
        tqdm.write(f"Error: '{root}' is not a valid directory.")
        sys.exit(1)

    denylist = load_denylist(args.denylist_file)

    tqdm.write(f"Scanning '{root}' for FLAC files...")
    albums, skipped = scan_albums(root)

    if not albums:
        tqdm.write("No albums with ALBUM tags found. Nothing to do.")
        sys.exit(0)

    tqdm.write(f"\nFound {len(albums)} album(s) across {sum(len(v) for v in albums.values())} track(s).")
    if skipped:
        tqdm.write(f"({len(skipped)} file(s) skipped due to missing/unreadable tags.)")

    if args.dry_run:
        tqdm.write("\n--- DRY RUN: no files will be modified ---")

    album_items = sorted(albums.items())
    progress = tqdm(album_items, desc="Albums", unit="album")
    skipped_albums = []

    for (artist, album), files in progress:
        progress.set_postfix_str(f"{artist} - {album}"[:60])
        tqdm.write(f"\n'{artist}' - '{album}'  ({len(files)} track(s))")

        tags = resolve_album_tags(
            api_key=api_key,
            artist=artist,
            album=album,
            files=files,
            min_weight=args.min_weight,
            denylist=denylist,
            delay=args.delay,
            interactive=not args.no_prompt,
        )

        if not tags:
            tqdm.write("    Skipping this album (genre left untouched).")
            skipped_albums.append((artist, album))
            time.sleep(args.delay)
            continue

        genre_string = ";".join(tags)
        tqdm.write(f"    Tags: {genre_string}")

        for f in tqdm(files, desc="  Tracks", unit="file", leave=False):
            try:
                apply_genre_tag(f, genre_string, dry_run=args.dry_run)
                action = "Would set" if args.dry_run else "Set"
                tqdm.write(f"      {action} GENRE on: {f.name}")
            except Exception as e:
                tqdm.write(f"      [ERROR] Failed to write tag to {f}: {e}")

        time.sleep(args.delay)

    if skipped_albums:
        tqdm.write(f"\n{len(skipped_albums)} album(s) were skipped (no tags found):")
        for artist, album in skipped_albums:
            tqdm.write(f"  - '{artist}' - '{album}'")

        if not args.no_log:
            log_path = Path(args.log_file).expanduser()
            try:
                with log_path.open("w", encoding="utf-8") as f:
                    f.write("Albums skipped (no Last.fm tags found automatically)\n")
                    f.write("=" * 60 + "\n\n")
                    for artist, album in skipped_albums:
                        f.write(f"{artist} - {album}\n")
                        f.write(f"  {build_lastfm_search_url(artist, album)}\n\n")
                tqdm.write(f"\nWrote skipped-album list to: {log_path}")
            except OSError as e:
                tqdm.write(f"[ERROR] Could not write log file {log_path}: {e}")

    tqdm.write("\nDone." if not args.dry_run else "\nDry run complete. Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()