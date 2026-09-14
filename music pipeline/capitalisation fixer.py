"""
lastfm_capitalization_fixer.py

Walks a folder of FLAC files and fixes the capitalization of the TITLE,
ARTIST, ALBUMARTIST, and ALBUM tags to match how each is actually spelled
on Last.fm (e.g. "AC/DC" instead of "Ac/Dc", "Sigur Ros" -> "Sigur Rós").
It also normalizes TRACKNUMBER to a zero-padded "n/m" format (e.g. "05/12"
instead of "5/12").

This only ever changes capitalization/spelling to match a Last.fm entry --
it never invents new metadata. If Last.fm has no page matching a tag at
all (ignoring case), that tag is left untouched, UNLESS you supply a
Last.fm URL for it (see below).

WHEN YOU GET ASKED, AND WHEN YOU DON'T:
    - A change that's ONLY a difference in case (e.g. 'Brand New Eyes' ->
      'brand new eyes') is applied automatically. You're never asked
      about pure-case fixes.
    - A substantive change (different spelling/wording, not just case) is
      approved ONCE per unique value, the first time it's found -- not
      once per file. That one decision is cached and silently reused for
      every other track that shares the same artist/album/title, so
      fixing an album's name applies it to the whole album in one prompt,
      not once per track.
    - Ambiguous cases (multiple distinct Last.fm entries matching
      case-insensitively) always prompt you to pick, same as before --
      picking one there already counts as approval.
    - At any prompt: [a]ll applies every remaining change (of any kind)
      without asking again; [skip-all] rejects everything remaining;
      [q]uit stops the run cleanly, keeping whatever's already been
      decided/written.

MULTI-ARTIST TAGS:
    If ARTIST or ALBUMARTIST contains "; " (this script's convention for
    multiple artists, e.g. "South Arcade; Bilmuri"), each name is looked
    up and corrected on Last.fm individually, then rejoined with "; " --
    Last.fm has no page for the combined string, so it's never queried
    as one. Album and title lookups always use ALBUMARTIST (falling back
    to ARTIST), and only its first name if that also contains "; ", since
    that's normally the "clean" canonical artist for the release.

SPEED: title lookups are the expensive part of this (one Last.fm request
per distinct track, versus far fewer distinct artists/albums). To avoid
that, once an album has been resolved this script fetches that album's
full tracklist from Last.fm ONE time (album.getInfo) and matches each
local file's title against it directly -- no extra request per track.

SAFETY: matching by track number against an album's Last.fm tracklist is
only trusted when the resulting name is still reasonably similar to what
you already have tagged (multi-disc/deluxe editions can otherwise make
"track 4" on Last.fm correspond to a totally different song). A
low-similarity rank match falls back to an individual track.search
instead of being applied blind.

PERSISTENT CACHE: every Last.fm lookup result AND every approval decision
you make is saved to disk (default: ~/.lastfm_genre_tagger/
capitalization_cache.json) as you go. If the script is interrupted --
Ctrl+C, a crash, choosing [q]uit -- nothing is lost: re-running the same
folder reuses everything already resolved/decided, with no repeated
network requests or repeated prompts. Use --no-cache to disable this, or
--clear-cache to start fresh.

Fixing via a Last.fm URL:
    If Last.fm's search comes up empty (or you don't trust the automatic
    match), paste a Last.fm page URL when prompted, e.g.:
        https://www.last.fm/music/Sigur+Rós/_/Svefn-g-englar
    Read straight from the URL's path (no scraping needed) -- see
    parse_lastfm_music_url() for details.

API KEY STORAGE:
    Same encrypted-key setup as lastfm_genre_tagger.py, and by default
    reads the same key file, so if you've already run:
        python lastfm_genre_tagger.py --set-api-key
    you don't need to do anything else here. Otherwise:
        python lastfm_capitalization_fixer.py --set-api-key

Requirements:
    pip install mutagen requests tqdm cryptography

Usage:
    python lastfm_capitalization_fixer.py --set-api-key   # one-time
    python lastfm_capitalization_fixer.py /path/to/music/folder
    python lastfm_capitalization_fixer.py /path/to/music/folder --dry-run
    python lastfm_capitalization_fixer.py /path/to/music/folder --fields artist,album,tracknumber
    python lastfm_capitalization_fixer.py /path/to/music/folder --no-prompt
"""

import argparse
import base64
import difflib
import getpass
import json
import os
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from mutagen.flac import FLAC
from tqdm import tqdm

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

DEFAULT_KEY_FILE = Path.home() / ".lastfm_genre_tagger" / "api_key.enc"
DEFAULT_CACHE_FILE = Path.home() / ".lastfm_genre_tagger" / "capitalization_cache.json"
DEFAULT_LOG_FILE = "capitalization_skipped.log"
PBKDF2_ITERATIONS = 480_000

VALID_FIELDS = {"title", "artist", "album", "tracknumber"}
DEFAULT_FIELDS = "title,artist,album,tracknumber"

MULTI_ARTIST_SEPARATOR = "; "
TRACKLIST_RANK_SIMILARITY_THRESHOLD = 0.6


class QuitRequested(Exception):
    """Raised when the user chooses [q]uit at any approval prompt."""
    pass


# --------------------------------------------------------------------------
# Encrypted API key handling (identical scheme to lastfm_genre_tagger.py)
# --------------------------------------------------------------------------

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def save_encrypted_api_key(api_key: str, password: str, path: Path):
    salt = os.urandom(16)
    fernet_key = _derive_fernet_key(password, salt)
    token = Fernet(fernet_key).encrypt(api_key.encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(salt + b"\n" + token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_encrypted_api_key(password: str, path: Path) -> str:
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
    tqdm.write("Setting up your Last.fm API key.")
    tqdm.write("Don't have one? Create one free at https://www.last.fm/api/account/create")
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


def unlock_api_key(path: Path) -> str:
    if not path.is_file():
        tqdm.write(f"No encrypted API key found at: {path}")
        tqdm.write("Run this first:  python lastfm_capitalization_fixer.py --set-api-key")
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
# Persistent cache (Last.fm results + approval decisions)
# --------------------------------------------------------------------------

def _tuplify(obj):
    """Recursively turn JSON-decoded lists back into hashable tuples (for dict keys)."""
    if isinstance(obj, list):
        return tuple(_tuplify(x) for x in obj)
    return obj


CACHE_NAMES = ("artist_cache", "album_cache", "track_cache", "album_info_cache",
               "tracklist_cache", "tracknumber_decisions")


def load_caches(path: Path):
    caches = {name: {} for name in CACHE_NAMES}
    if not path.is_file():
        return caches
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        tqdm.write(f"[WARN] Could not read cache file {path} ({e}); starting with an empty cache.")
        return caches

    for name in CACHE_NAMES:
        for key, value in raw.get(name, []):
            caches[name][_tuplify(key)] = value

    total = sum(len(d) for d in caches.values())
    if total:
        tqdm.write(f"Loaded {total} cached Last.fm result(s)/decision(s) from {path}")
    return caches


def save_caches(path: Path, caches: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: list(caches[name].items()) for name in CACHE_NAMES}
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp_path.replace(path)
    except OSError as e:
        tqdm.write(f"[WARN] Could not save cache to {path}: {e}")


# --------------------------------------------------------------------------
# FLAC scanning
# --------------------------------------------------------------------------

def find_flac_files(root: Path):
    yield from root.rglob("*.flac")


def get_tag(audio: FLAC, key: str) -> Optional[str]:
    val = audio.get(key, [None])[0]
    return val.strip() if val else None


class TrackInfo:
    __slots__ = ("path", "title", "artist", "albumartist", "album", "trackno_raw", "tracktotal_raw")

    def __init__(self, path, title, artist, albumartist, album, trackno_raw, tracktotal_raw):
        self.path = path
        self.title = title
        self.artist = artist
        self.albumartist = albumartist
        self.album = album
        self.trackno_raw = trackno_raw
        self.tracktotal_raw = tracktotal_raw

    def album_key(self):
        """Grouping key for tracklist/track-count lookups: (artist_lower, album_lower)."""
        context_artist = self.albumartist or self.artist
        if not self.album or not context_artist:
            return None
        return (context_artist.lower(), self.album.lower())


def scan_tracks(root: Path):
    tracks = []
    unreadable = []
    for flac_path in find_flac_files(root):
        try:
            audio = FLAC(flac_path)
        except Exception as e:
            tqdm.write(f"  [WARN] Could not read {flac_path}: {e}")
            unreadable.append(flac_path)
            continue
        tracks.append(TrackInfo(
            path=flac_path,
            title=get_tag(audio, "title"),
            artist=get_tag(audio, "artist"),
            albumartist=get_tag(audio, "albumartist"),
            album=get_tag(audio, "album"),
            trackno_raw=get_tag(audio, "tracknumber"),
            tracktotal_raw=get_tag(audio, "tracktotal") or get_tag(audio, "totaltracks"),
        ))
    return tracks, unreadable


def split_multi_artist(raw: str):
    """Split on the "; " multi-artist convention. Returns [raw] unchanged if not present."""
    if MULTI_ARTIST_SEPARATOR in raw:
        return [p.strip() for p in raw.split(MULTI_ARTIST_SEPARATOR) if p.strip()]
    return [raw]


def primary_artist(raw: Optional[str]) -> Optional[str]:
    """The first name in a possibly-multi-artist string; used for Last.fm query context."""
    if not raw:
        return raw
    return split_multi_artist(raw)[0]


# --------------------------------------------------------------------------
# Last.fm API queries
# --------------------------------------------------------------------------

def _lastfm_request(params: dict, label: str):
    try:
        resp = requests.get(LASTFM_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        tqdm.write(f"    [ERROR] Last.fm request failed for '{label}': {e}")
        return None
    except ValueError:
        tqdm.write(f"    [ERROR] Bad JSON from Last.fm for '{label}'")
        return None
    if "error" in data:
        tqdm.write(f"    [ERROR] Last.fm API error for '{label}': {data.get('message')}")
        return None
    return data


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def search_artist_candidates(api_key: str, name: str):
    data = _lastfm_request(
        {"method": "artist.search", "artist": name, "api_key": api_key, "format": "json", "limit": 30},
        f"artist.search:{name}",
    )
    if not data:
        return []
    matches = _as_list(data.get("results", {}).get("artistmatches", {}).get("artist"))
    return [(m.get("name", "").strip(), _to_int(m.get("listeners"))) for m in matches if m.get("name")]


def search_track_candidates(api_key: str, artist: str, title: str):
    data = _lastfm_request(
        {"method": "track.search", "track": title, "artist": artist, "api_key": api_key,
         "format": "json", "limit": 30},
        f"track.search:{artist} - {title}",
    )
    if not data:
        return []
    matches = _as_list(data.get("results", {}).get("trackmatches", {}).get("track"))
    out = []
    for m in matches:
        name = m.get("name", "").strip()
        m_artist = m.get("artist", "").strip()
        if not name or m_artist.lower() != artist.lower():
            continue
        out.append((name, _to_int(m.get("listeners"))))
    return out


def get_album_info(api_key: str, artist: str, album: str, cache: dict, delay: float):
    """
    Fetch album.getInfo for (artist, album). Cached by (artist.lower(), album.lower()).
    Returns {"name","listeners","tracks":[(num_or_None,name),...]} or None.
    """
    key = (artist.lower(), album.lower())
    if key in cache:
        return cache[key]

    data = _lastfm_request(
        {"method": "album.getinfo", "artist": artist, "album": album, "api_key": api_key, "format": "json"},
        f"album.getinfo:{artist} - {album}",
    )
    time.sleep(delay)

    if not data:
        cache[key] = None
        return None

    album_data = data.get("album", {})
    name = album_data.get("name", album).strip()
    listeners = _to_int(album_data.get("listeners"))

    raw_tracks = _as_list(album_data.get("tracks", {}).get("track"))
    tracks = []
    for t in raw_tracks:
        t_name = t.get("name", "").strip()
        if not t_name:
            continue
        rank = t.get("@attr", {}).get("rank")
        try:
            num = int(rank)
        except (TypeError, ValueError):
            num = None
        tracks.append((num, t_name))

    result = {"name": name, "listeners": listeners, "tracks": tracks}
    cache[key] = result
    return result


def search_album_candidates(api_key: str, artist: str, album: str, album_info_cache: dict, delay: float):
    data = _lastfm_request(
        {"method": "album.search", "album": album, "api_key": api_key, "format": "json", "limit": 30},
        f"album.search:{artist} - {album}",
    )
    if not data:
        return []
    matches = _as_list(data.get("results", {}).get("albummatches", {}).get("album"))

    pairs = []
    seen = set()
    for m in matches:
        name = m.get("name", "").strip()
        m_artist = m.get("artist", "").strip()
        if not name or m_artist.lower() != artist.lower():
            continue
        key = (name, m_artist)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((name, m_artist))

    out = []
    for name, m_artist in pairs:
        info = get_album_info(api_key, m_artist, name, album_info_cache, delay)
        out.append((name, info["listeners"] if info else 0))
    return out


def get_tracklist_for_album(api_key: str, album_artist_query: str, album_context_artist: str, album_name: str,
                             album_info_cache: dict, tracklist_cache: dict, delay: float):
    """
    Fetch the Last.fm tracklist for an album, cached under the ORIGINAL
    (album_context_artist, album_name) as found in the file tags -- so
    lookups from other tracks in the same local album always hit cache,
    even though the actual Last.fm query uses album_artist_query (the
    "clean" primary-artist form used for searching).
    """
    key = (album_context_artist.lower(), album_name.lower())
    if key in tracklist_cache:
        return tracklist_cache[key]

    info = get_album_info(api_key, album_artist_query, album_name, album_info_cache, delay)
    tracks = info["tracks"] if info else []
    tracklist_cache[key] = tracks
    return tracks


# --------------------------------------------------------------------------
# Last.fm URL parsing (manual correction path)
# --------------------------------------------------------------------------

def build_lastfm_search_url(entity_type: str, original: str, context_artist: Optional[str] = None):
    if entity_type == "artist":
        path, q = "artists", original
    elif entity_type == "album":
        path = "albums"
        q = f"{context_artist} {original}" if context_artist else original
    else:
        path = "tracks"
        q = f"{context_artist} {original}" if context_artist else original
    return f"https://www.last.fm/search/{path}?q={urllib.parse.quote_plus(q)}"


def _parse_music_path(url: str):
    parsed = urllib.parse.urlparse(url)
    if "last.fm" not in parsed.netloc.lower():
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments or segments[0] != "music" or len(segments) < 2:
        return None
    rest = segments[1:]
    artist = urllib.parse.unquote_plus(rest[0])
    album = None
    title = None
    if len(rest) >= 2:
        if rest[1] == "_":
            if len(rest) >= 3:
                title = urllib.parse.unquote_plus(rest[2])
        else:
            album = urllib.parse.unquote_plus(rest[1])
            if len(rest) >= 3:
                title = urllib.parse.unquote_plus(rest[2])
    return {"artist": artist, "album": album, "title": title}


def parse_lastfm_music_url(url: str):
    """
    Parse artist/album/title straight out of a last.fm /music/... URL's
    path -- trustworthy with no network call, since a URL copied off the
    page already has last.fm's canonical, correctly-cased spelling. A
    best-effort redirect-follow is also attempted (in case you typed the
    URL by hand with the wrong case), but is silently skipped on any
    failure -- a URL you already know is right shouldn't be blocked by
    last.fm being briefly down.
    """
    direct = _parse_music_path(url)
    if not direct:
        tqdm.write("    [ERROR] That doesn't look like a last.fm /music/... page.")
        return None
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True)
        if resp.status_code == 200 and resp.url != url:
            redirected = _parse_music_path(resp.url)
            if redirected:
                return redirected
    except requests.RequestException:
        pass
    return direct


def prompt_for_url_correction(entity_type: str):
    url = input("    Paste a last.fm URL for the correct entry: ").strip()
    if not url:
        return None, None
    parsed = parse_lastfm_music_url(url)
    if not parsed:
        return None, None
    value = parsed.get(entity_type)
    if not value:
        tqdm.write(f"    That URL didn't include a {entity_type} -- try a more specific last.fm page.")
        return None, None
    return value, parsed


# --------------------------------------------------------------------------
# Approval prompts
# --------------------------------------------------------------------------

def is_case_only(old: str, new: str) -> bool:
    return old != new and old.lower() == new.lower()


def get_batch_approval(review_state: dict, message: str) -> str:
    """
    Show `message` and ask for approval, honoring a running "apply all" /
    "skip all" choice in review_state["mode"]. Returns "apply", "skip",
    or raises QuitRequested.
    """
    if review_state["mode"] == "all":
        return "apply"
    if review_state["mode"] == "skip-all":
        return "skip"

    tqdm.write(message)
    while True:
        choice = input(
            "    Apply? [y]es / [n]o / [a]ll remaining / [skip-all] remaining / [q]uit: "
        ).strip().lower()
        if choice in ("y", "yes", ""):
            return "apply"
        if choice in ("n", "no"):
            return "skip"
        if choice in ("a", "all"):
            review_state["mode"] = "all"
            return "apply"
        if choice in ("skip-all", "sa"):
            review_state["mode"] = "skip-all"
            return "skip"
        if choice in ("q", "quit"):
            raise QuitRequested()
        tqdm.write("    Please enter y, n, a, skip-all, or q.")


def dedupe_candidates(candidates):
    best = {}
    for name, listeners in candidates:
        if name not in best or listeners > best[name]:
            best[name] = listeners
    return sorted(best.items(), key=lambda kv: -kv[1])


def prompt_disambiguate(entity_type: str, original: str, entries, context_artist: Optional[str] = None):
    """
    entries: list of (name, listeners), sorted by listeners desc. May be empty.
    Returns (chosen_value_or_None, parsed_url_dict_or_None). Raises
    QuitRequested on [q]uit.
    """
    search_url = build_lastfm_search_url(entity_type, original, context_artist)

    if entries:
        tqdm.write(f"    Multiple Last.fm {entity_type} entries match '{original}' (case-insensitive):")
        for i, (name, listeners) in enumerate(entries, start=1):
            tqdm.write(f"      {i}) {name!r}  --  {listeners:,} listeners")
        tqdm.write(f"    Search last.fm yourself: {search_url}")
        prompt = (f"    Pick 1-{len(entries)}, [m]anually type the correct spelling, "
                  f"[u]se a last.fm URL, or [s]kip / leave unchanged: ")
    else:
        tqdm.write(f"    No Last.fm {entity_type} entry found automatically for '{original}'.")
        tqdm.write(f"    Search last.fm yourself: {search_url}")
        prompt = "    [m]anually type the correct spelling, [u]se a last.fm URL, or [s]kip / leave unchanged: "

    while True:
        choice = input(prompt).strip().lower()

        if choice in ("s", "skip", ""):
            return None, None
        if choice in ("q", "quit"):
            raise QuitRequested()
        if choice in ("m", "manual"):
            raw = input("    Enter the correct spelling exactly: ").strip()
            return (raw if raw else None), None
        if choice in ("u", "url"):
            value, parsed = prompt_for_url_correction(entity_type)
            if value is None:
                continue
            return value, parsed
        if entries and choice.isdigit() and 1 <= int(choice) <= len(entries):
            return entries[int(choice) - 1][0], None

        tqdm.write("    Please enter a valid option.")


def seed_from_url(parsed: dict, track: TrackInfo, album_context_artist,
                   artist_cache: dict, album_cache: dict, track_cache: dict):
    """Opportunistically pre-fill the other caches from a URL's parsed info, where it clearly matches."""
    if not parsed:
        return
    p_artist, p_album, p_title = parsed.get("artist"), parsed.get("album"), parsed.get("title")

    if p_artist:
        for raw in (track.artist, track.albumartist):
            if not raw:
                continue
            for part in split_multi_artist(raw):
                if part.lower() == p_artist.lower():
                    artist_cache.setdefault(part.lower(), p_artist)

    if p_album and album_context_artist and track.album and track.album.lower() == p_album.lower():
        album_cache.setdefault((album_context_artist.lower(), track.album.lower()), p_album)

    if p_title and track.artist and track.title and track.title.lower() == p_title.lower():
        track_cache.setdefault((track.artist.lower(), track.title.lower()), p_title)


def resolve(entity_type: str, key, original: str, cache: dict, fetch_fn, interactive: bool,
            skipped_log: list, review_state: dict, seed_ctx=None, context_artist: Optional[str] = None,
            usage_count: int = 0):
    """
    Generic resolve-with-cache-and-approval helper.
      - Cache hit: return immediately, no network/prompt.
      - Exactly one automatic match: apply silently if case-only-different
        (or identical); otherwise ask for approval ONCE (result cached).
      - Ambiguous / no match: prompt to disambiguate / manual / URL / skip
        (the user's choice there already counts as approval).
    Raises QuitRequested if the user quits at any prompt.
    """
    if key in cache:
        return cache[key]

    raw_candidates = fetch_fn()
    entries = dedupe_candidates(raw_candidates)
    entries = [(n, l) for n, l in entries if n.lower() == original.lower()]

    if len(entries) == 1:
        candidate = entries[0][0]
        if candidate == original or is_case_only(original, candidate) or not interactive:
            cache[key] = candidate
            return candidate

        count_str = f" (used by {usage_count} track{'s' if usage_count != 1 else ''})" if usage_count > 1 else ""
        msg = f"    Last.fm {entity_type} correction: {original!r} -> {candidate!r}{count_str}"
        decision = get_batch_approval(review_state, msg)
        chosen = candidate if decision == "apply" else None
        cache[key] = chosen
        if chosen is None:
            skipped_log.append((entity_type, original, "user declined automatic correction"))
        return chosen

    if len(entries) > 1 and not interactive:
        chosen = entries[0][0]
        cache[key] = chosen
        skipped_log.append((entity_type, original, f"auto-picked highest-listener entry: {chosen!r}"))
        return chosen

    if not entries and not interactive:
        cache[key] = None
        skipped_log.append((entity_type, original, "no matching Last.fm entry found"))
        return None

    chosen, parsed = prompt_disambiguate(entity_type, original, entries, context_artist)
    cache[key] = chosen

    if parsed and seed_ctx:
        track, album_context_artist, artist_cache, album_cache, track_cache = seed_ctx
        seed_from_url(parsed, track, album_context_artist, artist_cache, album_cache, track_cache)

    if chosen is None:
        reason = "no matching Last.fm entry found" if not entries else "user skipped disambiguation"
        skipped_log.append((entity_type, original, reason))

    return chosen


def match_title_in_tracklist(track_number: Optional[int], title: str, tracklist):
    """
    Find this track's corrected title in an already-fetched album tracklist.
    Exact case-insensitive name match is trusted outright. A track-number
    match is only trusted if the candidate name is still reasonably similar
    (guards against multi-disc/deluxe editions misaligning rank numbers).
    """
    if not tracklist:
        return None
    title_lower = title.lower()
    for _, name in tracklist:
        if name.lower() == title_lower:
            return name
    if track_number is not None:
        for num, name in tracklist:
            if num == track_number:
                similarity = difflib.SequenceMatcher(None, title_lower, name.lower()).ratio()
                return name if similarity >= TRACKLIST_RANK_SIMILARITY_THRESHOLD else None
    return None


# --------------------------------------------------------------------------
# TRACKNUMBER normalization
# --------------------------------------------------------------------------

def parse_n_m(trackno_raw: Optional[str], tracktotal_raw: Optional[str]):
    n = None
    m = None
    if trackno_raw:
        raw = trackno_raw.strip()
        if "/" in raw:
            n_part, m_part = raw.split("/", 1)
        else:
            n_part, m_part = raw, None
        try:
            n = int(n_part.strip())
        except (TypeError, ValueError):
            n = None
        if m_part:
            try:
                m = int(m_part.strip())
            except (TypeError, ValueError):
                m = None
    if m is None and tracktotal_raw:
        try:
            m = int(tracktotal_raw.strip())
        except (TypeError, ValueError):
            m = None
    return n, m


def format_track_number(n: int, m: int) -> str:
    width = len(str(m))
    return f"{str(n).zfill(width)}/{str(m).zfill(width)}"


def show_diff(t: TrackInfo, updates: dict):
    tqdm.write(f"\n{t.path.name}")
    for field_name, new_value in updates.items():
        old_value = t.trackno_raw if field_name == "tracknumber" else getattr(t, field_name)
        tqdm.write(f"    {field_name}: {old_value!r} -> {new_value!r}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fix TITLE/ARTIST/ALBUMARTIST/ALBUM/TRACKNUMBER formatting on FLAC files to match Last.fm."
    )
    parser.add_argument("folder", type=str, nargs="?", default=".",
                         help="Folder containing FLAC files, searched recursively (default: current directory)")
    parser.add_argument("--set-api-key", action="store_true",
                         help="Prompt for your Last.fm API key and a password, encrypt and save it, then exit.")
    parser.add_argument("--key-file", type=str, default=str(DEFAULT_KEY_FILE),
                         help=f"Path to the encrypted API key file (default: {DEFAULT_KEY_FILE})")
    parser.add_argument("--fields", type=str, default=DEFAULT_FIELDS,
                         help=f"Comma-separated subset of: title,artist,album,tracknumber (default: {DEFAULT_FIELDS})")
    parser.add_argument("--delay", type=float, default=0.25,
                         help="Seconds to wait between Last.fm requests. Default 0.25")
    parser.add_argument("--no-prompt", action="store_true",
                         help="Never pause for disambiguation or unmatched entries; auto-pick the "
                              "entry with the most listeners and leave unmatched tags untouched.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Show what would change without writing any tags to disk or asking for approval.")
    parser.add_argument("--auto-apply", action="store_true",
                         help="Don't ask for approval on substantive changes either -- apply everything "
                              "automatically. Case-only changes are always automatic regardless.")
    parser.add_argument("--cache-file", type=str, default=str(DEFAULT_CACHE_FILE),
                         help=f"Where to persist Last.fm results + approval decisions (default: {DEFAULT_CACHE_FILE})")
    parser.add_argument("--no-cache", action="store_true",
                         help="Don't load or save the persistent cache for this run.")
    parser.add_argument("--clear-cache", action="store_true",
                         help="Delete the cache file before running (forces everything to be re-resolved).")
    parser.add_argument("--log-file", type=str, default=DEFAULT_LOG_FILE,
                         help=f"Where to write a summary of items that couldn't be auto-fixed (default: {DEFAULT_LOG_FILE})")
    parser.add_argument("--no-log", action="store_true", help="Don't write the skipped-items log file.")

    args = parser.parse_args()

    fields = {f.strip().lower() for f in args.fields.split(",") if f.strip()}
    bad_fields = fields - VALID_FIELDS
    if bad_fields:
        tqdm.write(f"[ERROR] Unknown --fields value(s): {', '.join(sorted(bad_fields))}. "
                   f"Valid options: {', '.join(sorted(VALID_FIELDS))}")
        sys.exit(1)

    key_path = Path(args.key_file).expanduser()
    if args.set_api_key:
        setup_api_key(key_path)
        sys.exit(0)
    api_key = unlock_api_key(key_path)

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        tqdm.write(f"Error: '{root}' is not a valid directory.")
        sys.exit(1)

    cache_path = Path(args.cache_file).expanduser()
    if args.clear_cache and cache_path.is_file():
        cache_path.unlink()
        tqdm.write(f"Cleared cache: {cache_path}")

    tqdm.write(f"Scanning '{root}' for FLAC files...")
    tracks, unreadable = scan_tracks(root)
    if not tracks:
        tqdm.write("No readable FLAC files found. Nothing to do.")
        sys.exit(0)
    tqdm.write(f"Found {len(tracks)} track(s).")
    if unreadable:
        tqdm.write(f"({len(unreadable)} file(s) could not be read.)")

    # --- Pre-pass: album grouping, track-total determination, usage counts ---
    album_groups = defaultdict(list)
    for t in tracks:
        k = t.album_key()
        if k is not None:
            album_groups[k].append(t)

    album_total_tracks = {}
    for k, group in album_groups.items():
        m_candidates = [m for m in (parse_n_m(f.trackno_raw, f.tracktotal_raw)[1] for f in group) if m]
        if m_candidates:
            album_total_tracks[k] = max(m_candidates)
        elif len(group) >= 2:
            album_total_tracks[k] = len(group)

    artist_part_counts = Counter()
    for t in tracks:
        for raw in (t.artist, t.albumartist):
            if raw:
                for part in split_multi_artist(raw):
                    artist_part_counts[part.lower()] += 1
    album_counts = Counter(t.album_key() for t in tracks if t.album_key() is not None)

    # --- Caches ---
    if args.no_cache:
        caches = {name: {} for name in CACHE_NAMES}
    else:
        caches = load_caches(cache_path)
    artist_cache = caches["artist_cache"]
    album_cache = caches["album_cache"]
    track_cache = caches["track_cache"]
    album_info_cache = caches["album_info_cache"]
    tracklist_cache = caches["tracklist_cache"]
    tracknumber_decisions = caches["tracknumber_decisions"]

    def persist():
        if not args.no_cache:
            save_caches(cache_path, caches)

    if args.dry_run or args.auto_apply:
        review_state = {"mode": "all"}
    else:
        review_state = {"mode": "ask"}

    skipped_log = []
    changed_files = 0
    changed_fields = 0
    track_search_calls_saved = 0
    needs_tracklist = "title" in fields or "tracknumber" in fields

    if args.dry_run:
        tqdm.write("\n--- DRY RUN: no files will be modified, everything will be shown ---")

    quit_early = False

    try:
        for idx, t in enumerate(tqdm(tracks, desc="Tracks", unit="file"), start=1):
            updates = {}
            album_context_artist = t.albumartist or t.artist
            lookup_artist = primary_artist(album_context_artist)

            # --- ARTIST / ALBUMARTIST: split multi-artist tags, resolve each name ---
            if "artist" in fields:
                for field_name, raw_value in (("artist", t.artist), ("albumartist", t.albumartist)):
                    if not raw_value:
                        continue
                    parts = split_multi_artist(raw_value)
                    corrected_parts = []
                    any_change = False
                    for part in parts:
                        pkey = part.lower()
                        corrected = resolve(
                            "artist", pkey, part, artist_cache,
                            fetch_fn=lambda p=part: search_artist_candidates(api_key, p),
                            interactive=not args.no_prompt, skipped_log=skipped_log, review_state=review_state,
                            seed_ctx=(t, album_context_artist, artist_cache, album_cache, track_cache),
                            usage_count=artist_part_counts.get(pkey, 0),
                        )
                        time.sleep(args.delay)
                        corrected_parts.append(corrected if corrected else part)
                        if corrected and corrected != part:
                            any_change = True
                    if any_change:
                        new_value = MULTI_ARTIST_SEPARATOR.join(corrected_parts)
                        if new_value != raw_value:
                            updates[field_name] = new_value

            # --- ALBUM ---
            corrected_album = None
            tracklist = []
            if t.album and album_context_artist:
                if "album" in fields:
                    akey = (album_context_artist.lower(), t.album.lower())
                    corrected_album = resolve(
                        "album", akey, t.album, album_cache,
                        fetch_fn=lambda: search_album_candidates(api_key, lookup_artist, t.album, album_info_cache, args.delay),
                        interactive=not args.no_prompt, skipped_log=skipped_log, review_state=review_state,
                        seed_ctx=(t, album_context_artist, artist_cache, album_cache, track_cache),
                        context_artist=album_context_artist,
                        usage_count=album_counts.get(t.album_key(), 0),
                    )
                    time.sleep(args.delay)
                    if corrected_album and corrected_album != t.album:
                        updates["album"] = corrected_album

                if needs_tracklist:
                    effective_album = corrected_album or t.album
                    tracklist = get_tracklist_for_album(
                        api_key, lookup_artist, album_context_artist, t.album, album_info_cache, tracklist_cache, args.delay
                    )
                    if not tracklist and effective_album != t.album:
                        tracklist = get_tracklist_for_album(
                            api_key, lookup_artist, album_context_artist, effective_album,
                            album_info_cache, tracklist_cache, args.delay
                        )

            # --- TITLE ---
            if "title" in fields and t.title and t.artist:
                tkey = (album_context_artist.lower() if album_context_artist else t.artist.lower(), t.title.lower())

                if tkey in track_cache:
                    corrected_title = track_cache[tkey]
                else:
                    trackno_n, _ = parse_n_m(t.trackno_raw, t.tracktotal_raw)
                    tl_match = match_title_in_tracklist(trackno_n, t.title, tracklist)

                    if tl_match:
                        track_search_calls_saved += 1
                        if tl_match == t.title or is_case_only(t.title, tl_match):
                            track_cache[tkey] = tl_match
                            corrected_title = tl_match
                        else:
                            msg = f"    Last.fm title correction: {t.title!r} -> {tl_match!r}"
                            decision = get_batch_approval(review_state, msg)
                            corrected_title = tl_match if decision == "apply" else None
                            track_cache[tkey] = corrected_title
                            if corrected_title is None:
                                skipped_log.append(("title", t.title, "user declined automatic correction"))
                    else:
                        corrected_title = resolve(
                            "title", tkey, t.title, track_cache,
                            fetch_fn=lambda: search_track_candidates(api_key, lookup_artist, t.title),
                            interactive=not args.no_prompt, skipped_log=skipped_log, review_state=review_state,
                            seed_ctx=(t, album_context_artist, artist_cache, album_cache, track_cache),
                            context_artist=lookup_artist,
                        )
                        time.sleep(args.delay)

                if corrected_title and corrected_title != t.title:
                    updates["title"] = corrected_title

            # --- TRACKNUMBER ---
            if "tracknumber" in fields:
                n, _ = parse_n_m(t.trackno_raw, t.tracktotal_raw)
                akey = t.album_key()
                m = album_total_tracks.get(akey) if akey is not None else parse_n_m(t.trackno_raw, t.tracktotal_raw)[1]

                if n is not None and m:
                    new_trackno = format_track_number(n, m)
                    if new_trackno != (t.trackno_raw or ""):
                        decision_key = akey if akey is not None else ("__file__", str(t.path))
                        if decision_key in tracknumber_decisions:
                            decision = tracknumber_decisions[decision_key]
                        else:
                            count = album_counts.get(akey, 1) if akey is not None else 1
                            label = t.album or t.title or t.path.name
                            who = f" by {album_context_artist}" if album_context_artist else ""
                            msg = (f"    Track numbers for '{label}'{who} will be reformatted "
                                   f"(e.g. {(t.trackno_raw or str(n))!r} -> {new_trackno!r}) for {count} track(s).")
                            decision = get_batch_approval(review_state, msg)
                            tracknumber_decisions[decision_key] = decision
                        if decision == "apply":
                            updates["tracknumber"] = new_trackno
                elif n is not None and not m:
                    skipped_log.append(("tracknumber", t.trackno_raw or str(n),
                                         f"{t.path}: couldn't determine total track count"))
                elif t.trackno_raw:
                    skipped_log.append(("tracknumber", t.trackno_raw, f"{t.path}: couldn't parse a track number"))

            # --- Write (everything left in `updates` is already approved) ---
            if updates:
                changed_files += 1
                changed_fields += len(updates)
                show_diff(t, updates)
                if not args.dry_run:
                    try:
                        audio = FLAC(t.path)
                        for field_name, new_value in updates.items():
                            audio[field_name] = [new_value]
                        audio.save()
                    except Exception as e:
                        tqdm.write(f"    [ERROR] Failed to write tags to {t.path}: {e}")

            if idx % 50 == 0:
                persist()

    except QuitRequested:
        tqdm.write("\nStopping here (quit requested); nothing further will be changed.")
        quit_early = True
    except KeyboardInterrupt:
        tqdm.write("\nInterrupted; progress so far is saved to the cache.")
        quit_early = True
    finally:
        persist()

    tqdm.write(f"\n{changed_files} file(s) had {changed_fields} tag(s) corrected.")
    if track_search_calls_saved:
        tqdm.write(f"({track_search_calls_saved} track title(s) matched directly from album tracklists, "
                    f"skipping an individual lookup for each.)")
    if not args.no_cache:
        tqdm.write(f"Cache saved to: {cache_path}")

    if skipped_log:
        tqdm.write(f"{len(skipped_log)} item(s) could not be auto-corrected (see log for details).")
        if not args.no_log:
            log_path = Path(args.log_file).expanduser()
            try:
                with log_path.open("w", encoding="utf-8") as f:
                    f.write("Items that could not be automatically corrected\n")
                    f.write("=" * 60 + "\n\n")
                    for entity_type, original, reason in skipped_log:
                        f.write(f"[{entity_type}] {original!r}: {reason}\n")
                tqdm.write(f"Wrote details to: {log_path}")
            except OSError as e:
                tqdm.write(f"[ERROR] Could not write log file {log_path}: {e}")

    if quit_early:
        tqdm.write("\nRun again on the same folder to pick up where you left off.")
    else:
        tqdm.write("\nDone." if not args.dry_run else "\nDry run complete. Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()