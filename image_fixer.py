#!/usr/bin/env python3
"""
FLAC Cover & Artist Image Manager
==================================

Consolidates four earlier scripts into one pipeline. End result for every
FLAC file in the target folder:

  * Exactly two embedded pictures, in this order:
        1. Front cover   (type 3) - identical across every track of an album
        2. Artist image  (type 8) - identical across every track by an artist
  * The front cover is >= MIN_RESOLUTIONxMIN_RESOLUTION and <= MAX_SIZE_BYTES.
  * Any other embedded picture types (back cover, leaflet, etc.) are dropped.

Pipeline:
  1. Scan for FLAC files, group by (album artist, album) and by album artist.
  2. For each album: find the best existing front cover across its tracks.
     If missing or it fails the quality bar, try to fix it (ffmpeg compress
     if just oversized, otherwise search Last.fm and let the user pick).
  3. For each artist: find an existing artist image, or search Last.fm.
  4. Write the final [front cover, artist image] pair into every track,
     skipping files that already have exactly that pair.

Requires: mutagen, Pillow, matplotlib, beautifulsoup4, curl_cffi, tqdm, ffmpeg.
"""

import os
import re
import sys
import time
import random
import shutil
import readline  # noqa: F401  (nicer input() editing)
import subprocess
import urllib.parse
from io import BytesIO
from pathlib import Path
from collections import defaultdict

from mutagen.flac import FLAC, Picture
from PIL import Image
from bs4 import BeautifulSoup
from tqdm import tqdm

# curl_cffi impersonates a real browser's TLS/HTTP2 fingerprint. Plain
# `requests` gets flagged by Last.fm's bot protection and rejected with
# 403/406 regardless of headers sent.  pip install curl_cffi
from curl_cffi import requests

import matplotlib

# ============================================================================
# CONFIG
# ============================================================================

RECURSIVE = True
MIN_RESOLUTION = 600          # pixels, both width and height
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB

IMPERSONATE = "chrome124"
MIN_DELAY, MAX_DELAY = 1.5, 3.5       # polite delay between artists/albums
IMAGE_PAGE_DELAY = (0.6, 1.4)         # delay before each detail-page fetch
MAX_RETRIES = 3
MAX_IMAGES_TO_OFFER = 12              # cap on gallery photos we'll browse

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# ============================================================================
# MATPLOTLIB PREVIEW
# ============================================================================

_backend_set = False
for _backend in ("GTK3Agg", "Qt5Agg", "TkAgg"):
    try:
        matplotlib.use(_backend)
        _backend_set = True
        break
    except Exception:
        continue

import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

if not _backend_set:
    print(
        "⚠ No interactive matplotlib backend available (tried GTK3Agg/Qt5Agg/TkAgg). "
        "Image previews will not be visible — install python3-gi (GTK) or PyQt5."
    )

_fig = None
_ax = None


def _init_preview():
    global _fig, _ax
    plt.ion()
    _fig, _ax = plt.subplots(figsize=(8, 8))
    _fig.canvas.manager.set_window_title("Cover / Artist Image Preview")


def show_image(image_data, title):
    """Preview raw image bytes in a persistent matplotlib window."""
    global _fig, _ax
    if _fig is None:
        _init_preview()
    try:
        _ax.clear()
        img = Image.open(BytesIO(image_data))
        _ax.imshow(img)
        _ax.axis("off")
        _ax.set_title(
            f"{title}\n{img.size[0]}x{img.size[1]} - {len(image_data) / 1024:.1f}KB",
            fontsize=11,
            pad=10,
        )
        _fig.tight_layout()
        plt.draw()
        plt.pause(0.1)
    except Exception as e:
        print(f"Could not preview image: {e}")


def close_preview():
    global _fig
    if _fig is not None:
        plt.close(_fig)
        _fig = None


# ============================================================================
# FLAC SCANNING / GROUPING
# ============================================================================

def find_flacs(folder):
    flac_files = []
    for root, dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".flac"):
                flac_files.append(os.path.join(root, f))
        if not RECURSIVE:
            break
    return flac_files


def read_album_artist_keys(path):
    """Return (album, album_artist) with sane fallbacks, or (None, None)."""
    try:
        audio = FLAC(path)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return None, None
    album = audio.get("album", [None])[0] or "Unknown Album"
    album_artist = (
        audio.get("albumartist", audio.get("artist", [None]))[0] or "Unknown Artist"
    )
    return album, album_artist


def group_by_album(flac_files):
    """{(album_artist, album): [file_path, ...]}"""
    albums = defaultdict(list)
    for path in flac_files:
        album, album_artist = read_album_artist_keys(path)
        if album and album_artist:
            albums[(album_artist, album)].append(path)
    return albums


def group_by_artist(flac_files):
    """{album_artist: [file_path, ...]}"""
    artists = defaultdict(list)
    for path in flac_files:
        _, album_artist = read_album_artist_keys(path)
        if album_artist:
            artists[album_artist].append(path)
    return artists


# ============================================================================
# QUALITY CHECK / COMPRESSION
# ============================================================================

def check_image_quality(image_data):
    """Return (is_valid, width, height, size_bytes, issue_str_or_None)."""
    try:
        img = Image.open(BytesIO(image_data))
        width, height = img.size
        size_bytes = len(image_data)
    except Exception as e:
        return False, 0, 0, 0, f"Error decoding image: {e}"

    issues = []
    if width < MIN_RESOLUTION or height < MIN_RESOLUTION:
        issues.append(f"resolution {width}x{height} < {MIN_RESOLUTION}x{MIN_RESOLUTION}")
    if size_bytes > MAX_SIZE_BYTES:
        issues.append(f"size {size_bytes / 1024 / 1024:.2f}MB > 2MB")

    return (len(issues) == 0), width, height, size_bytes, (", ".join(issues) or None)


def compress_image_ffmpeg(image_data, target_size_bytes):
    """Re-encode with ffmpeg, stepping quality down until under target size.
    Returns compressed bytes, or None if ffmpeg is unavailable / it fails."""
    if not FFMPEG_AVAILABLE:
        print("   ffmpeg not found on PATH — cannot compress.")
        return None

    tmp_dir = Path("/tmp/flac_cover_compress")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_input = tmp_dir / "in.jpg"
    temp_output = tmp_dir / "out.jpg"

    try:
        temp_input.write_bytes(image_data)
        original_size = len(image_data)
        compression_ratio = target_size_bytes / original_size

        if compression_ratio > 0.8:
            quality, step = 95, 2
        elif compression_ratio > 0.6:
            quality, step = 90, 3
        else:
            quality, step = 85, 5

        best_result, best_size = None, -1

        while quality >= 70:
            qscale = str(max(2, min(31, int(round((100 - quality) / 3.125)))))
            cmd = ["ffmpeg", "-y", "-i", str(temp_input), "-q:v", qscale, str(temp_output)]
            subprocess.run(cmd, capture_output=True, check=True)

            compressed = temp_output.read_bytes()
            compressed_size = len(compressed)
            print(f"   Trying quality {quality}: {compressed_size / 1024:.1f}KB")

            if compressed_size <= target_size_bytes and compressed_size > best_size:
                best_result, best_size = compressed, compressed_size
                if compressed_size > target_size_bytes * 0.9:
                    break  # close enough to target, stop early

            quality -= step

        if best_result is None:
            print("   Could not compress below target size while keeping quality reasonable.")
        return best_result

    except Exception as e:
        print(f"FFmpeg compression failed: {e}")
        return None
    finally:
        for f in (temp_input, temp_output):
            if f.exists():
                f.unlink()


# ============================================================================
# LAST.FM SCRAPING
# ============================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.last.fm/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

session = requests.Session(impersonate=IMPERSONATE)
session.headers.update(HEADERS)

_warmed_up = False


def warm_up_session():
    global _warmed_up
    if _warmed_up:
        return
    try:
        session.get("https://www.last.fm/", timeout=10)
    except Exception as e:
        print(f"Warm-up request failed (continuing anyway): {e}")
    _warmed_up = True


def get_with_retries(url, timeout=10):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code in (403, 406, 429):
                wait = attempt * 2 + random.uniform(0, 1.5)
                print(f"   Got {r.status_code}, retrying in {wait:.1f}s "
                      f"(attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            time.sleep(attempt * 2 + random.uniform(0, 1.5))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts")


IMAGE_PAGE_LINK_RE = re.compile(r'/music/[^"?#]+/\+images/[0-9a-f]{16,}')


def find_image_detail_links(gallery_html):
    soup = BeautifulSoup(gallery_html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if IMAGE_PAGE_LINK_RE.search(href):
            full = href if href.startswith("http") else f"https://www.last.fm{href}"
            if full not in seen:
                seen.add(full)
                links.append(full)
    return links


def get_og_image(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    og = soup.find("meta", property="og:image")
    if og and og.get("content") and "default_" not in og["content"]:
        return og["content"]
    return None


def build_gallery_url(artist, album=None):
    artist_q = urllib.parse.quote_plus(artist)
    if album:
        album_q = urllib.parse.quote_plus(album)
        return f"https://www.last.fm/music/{artist_q}/{album_q}/+images"
    return f"https://www.last.fm/music/{artist_q}/+images"


def get_gallery_sources(gallery_url):
    """Return a list of page URLs to lazily resolve into images, capped at
    MAX_IMAGES_TO_OFFER. Falls back to the gallery page itself (its own
    og:image) if no individual photo pages are found."""
    warm_up_session()
    print(f"Fetching: {gallery_url}")
    try:
        r = get_with_retries(gallery_url, timeout=10)
    except Exception as e:
        print(f"   Error fetching gallery page: {e}")
        return []

    detail_links = find_image_detail_links(r.text)
    if detail_links:
        print(f"   Found {len(detail_links)} photo page(s)"
              + (f" (capping at {MAX_IMAGES_TO_OFFER})"
                 if len(detail_links) > MAX_IMAGES_TO_OFFER else ""))
        return detail_links[:MAX_IMAGES_TO_OFFER]

    if get_og_image(r.text):
        print("   No individual photo pages — using gallery page's own image.")
        return [gallery_url]

    print("   No images found on Last.fm.")
    return []


def resolve_image_url(page_url, cache):
    """Fetch a single detail/gallery page and pull its og:image, on demand."""
    if page_url in cache:
        return cache[page_url]
    time.sleep(random.uniform(*IMAGE_PAGE_DELAY))
    try:
        rp = get_with_retries(page_url, timeout=10)
        img_url = get_og_image(rp.text)
    except Exception as e:
        print(f"   Could not fetch {page_url}: {e}")
        img_url = None
    cache[page_url] = img_url
    return img_url


def download_image(url):
    """Download image bytes, trying common URL variants if the exact URL 404s."""
    candidates = [url]
    if not re.search(r"\.(jpg|jpeg|png)$", url, re.IGNORECASE):
        candidates.append(url + ".jpg")
    if "/ar0/" in url:
        candidates.append(url.replace("/ar0/", "/770x0/"))
        if not re.search(r"\.(jpg|jpeg|png)$", url, re.IGNORECASE):
            candidates.append(url.replace("/ar0/", "/770x0/") + ".jpg")

    last_exc = None
    for candidate in candidates:
        try:
            r = get_with_retries(candidate, timeout=10)
            return r.content
        except Exception as e:
            last_exc = e
            continue
    print(f"   Could not download image from {url}: {last_exc}")
    return None


def interactive_lastfm_picker(artist, album, label):
    """Browse Last.fm images one at a time (y/n/p/s), returning validated
    bytes the user accepted, or None if they skipped / nothing worked."""
    gallery_url = build_gallery_url(artist, album)
    sources = get_gallery_sources(gallery_url)
    if not sources:
        return None

    resolved_cache = {}
    idx = 0
    while 0 <= idx < len(sources):
        page_url = sources[idx]
        print(f"\n→ Resolving image {idx + 1}/{len(sources)} for {label}")

        img_url = resolve_image_url(page_url, resolved_cache)
        if not img_url:
            idx += 1
            continue

        image_data = download_image(img_url)
        if not image_data:
            idx += 1
            continue

        is_valid, w, h, size, issue = check_image_quality(image_data)
        print(f"   {w}x{h}, {size / 1024:.1f}KB" + ("   ✓" if is_valid else f"   ⚠ {issue}"))
        show_image(image_data, f"{label} - {idx + 1}/{len(sources)}")

        choice = input("Use this image? [y]es / [n]ext / [p]revious / [s]kip: ").strip().lower()

        if choice == "y":
            if not is_valid:
                if size > MAX_SIZE_BYTES:
                    if input("   Too large — compress with ffmpeg? [Y/n]: ").strip().lower() != "n":
                        compressed = compress_image_ffmpeg(image_data, MAX_SIZE_BYTES)
                        if compressed:
                            image_data = compressed
                            is_valid, w, h, size, issue = check_image_quality(image_data)
                if not is_valid:
                    print(f"   ⚠ Still doesn't meet requirements: {issue}")
                    if input("   Use it anyway? [y/N]: ").strip().lower() != "y":
                        continue
            return image_data
        elif choice == "n":
            idx += 1
        elif choice == "p":
            idx = max(0, idx - 1)
        elif choice == "s":
            return None
        else:
            idx += 1

    print("No more images available.")
    return None


# ============================================================================
# EXISTING PICTURE HELPERS
# ============================================================================

def best_existing_front_cover(files):
    """Highest-resolution type-3 picture found across a set of FLAC files."""
    best_pic, best_score = None, -1
    for path in files:
        try:
            audio = FLAC(path)
        except Exception as e:
            print(f"Error reading pictures from {path}: {e}")
            continue
        for pic in audio.pictures:
            if pic.type == 3:
                score = pic.width * pic.height
                if score > best_score:
                    best_pic, best_score = pic, score
    return best_pic


def existing_artist_image(files):
    """First type-8 picture data found across a set of FLAC files."""
    for path in files:
        try:
            audio = FLAC(path)
        except Exception:
            continue
        for pic in audio.pictures:
            if pic.type == 8:
                return pic.data
    return None


def make_picture(image_data, pic_type, mime="image/jpeg"):
    pic = Picture()
    pic.type = pic_type
    pic.mime = mime
    pic.data = image_data
    return pic


def current_pair_matches(path, front_bytes, artist_bytes):
    """True if the file already has exactly [front(type3), artist(type8)]
    matching the given bytes, in that order."""
    try:
        audio = FLAC(path)
    except Exception:
        return False
    pics = audio.pictures
    expected_len = (1 if front_bytes else 0) + (1 if artist_bytes else 0)
    if len(pics) != expected_len:
        return False
    i = 0
    if front_bytes:
        if i >= len(pics) or pics[i].type != 3 or pics[i].data != front_bytes:
            return False
        i += 1
    if artist_bytes:
        if i >= len(pics) or pics[i].type != 8 or pics[i].data != artist_bytes:
            return False
    return True


def write_front_and_artist(path, front_bytes, artist_bytes):
    """Overwrite a file's pictures with exactly [front(type3), artist(type8)],
    dropping every other embedded picture type."""
    try:
        audio = FLAC(path)
        audio.clear_pictures()
        if front_bytes:
            audio.add_picture(make_picture(front_bytes, 3))
        if artist_bytes:
            audio.add_picture(make_picture(artist_bytes, 8))
        audio.save()
        return True
    except Exception as e:
        print(f"   ✗ Failed {os.path.basename(path)}: {e}")
        return False


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def resolve_album_cover(album_name, artist_name, files):
    """Return validated front-cover bytes for an album, or None if none
    could be obtained (existing cover kept as-is / album left without one)."""
    best_pic = best_existing_front_cover(files)
    candidate = best_pic.data if best_pic else None

    if candidate:
        is_valid, w, h, size, issue = check_image_quality(candidate)
        print(f"  Existing cover: {w}x{h}, {size / 1024:.1f}KB"
              + ("   ✓ meets requirements" if is_valid else f"   ⚠ {issue}"))
        if is_valid:
            return candidate

        # Oversized only -> try compressing before giving up on it.
        if size > MAX_SIZE_BYTES and w >= MIN_RESOLUTION and h >= MIN_RESOLUTION:
            if input("  Compress existing cover with ffmpeg? [Y/n]: ").strip().lower() != "n":
                compressed = compress_image_ffmpeg(candidate, MAX_SIZE_BYTES)
                if compressed:
                    ok, w2, h2, s2, _ = check_image_quality(compressed)
                    if ok:
                        print(f"  ✓ Compressed to {s2 / 1024:.1f}KB")
                        return compressed
    else:
        print("  No front cover found in any track.")

    # Need a replacement from Last.fm.
    if input(f"  Search Last.fm for a cover of '{album_name}'? [Y/n]: ").strip().lower() == "n":
        return candidate  # keep whatever (possibly None / substandard) we had

    replacement = interactive_lastfm_picker(artist_name, album_name, f"{artist_name} - {album_name}")
    if replacement:
        return replacement

    return candidate  # user skipped search; fall back to existing (may be None)


def resolve_artist_image(artist_name, files):
    """Return artist-image bytes for an artist, or None."""
    existing = existing_artist_image(files)
    if existing:
        return existing

    if input(f"  Search Last.fm for an artist image of '{artist_name}'? [Y/n]: ").strip().lower() == "n":
        return None

    return interactive_lastfm_picker(artist_name, None, artist_name)


def process_library(folder):
    if not os.path.isdir(folder):
        print(f"Error: {folder} is not a valid directory")
        sys.exit(1)

    print("Scanning for FLAC files...")
    flac_files = find_flacs(folder)
    if not flac_files:
        print("No FLAC files found.")
        sys.exit(0)
    print(f"Found {len(flac_files)} FLAC files.\n")

    albums = group_by_album(flac_files)
    artists = group_by_artist(flac_files)
    print(f"Found {len(albums)} albums across {len(artists)} artists.\n")

    try:
        # --- Step 1: resolve one validated cover per album ---
        album_covers = {}
        for (artist_name, album_name), files in sorted(albums.items()):
            print(f"{'=' * 60}\nAlbum: {album_name}   Artist: {artist_name}   "
                  f"({len(files)} track(s))\n{'=' * 60}")
            album_covers[(artist_name, album_name)] = resolve_album_cover(
                album_name, artist_name, files
            )
            print()

        # --- Step 2: resolve one validated artist image per artist ---
        artist_images = {}
        for artist_name, files in sorted(artists.items()):
            print(f"{'-' * 60}\nArtist: {artist_name}   ({len(files)} track(s))\n{'-' * 60}")
            artist_images[artist_name] = resolve_artist_image(artist_name, files)
            print()
    finally:
        close_preview()

    # --- Step 3: write final [front, artist] pair into every track ---
    print(f"{'=' * 60}\nApplying final images to all tracks...\n{'=' * 60}")
    updated, skipped, failed = 0, 0, 0
    for (artist_name, album_name), files in tqdm(albums.items(), desc="Writing"):
        front_bytes = album_covers.get((artist_name, album_name))
        artist_bytes = artist_images.get(artist_name)
        for path in files:
            if current_pair_matches(path, front_bytes, artist_bytes):
                skipped += 1
                continue
            if write_front_and_artist(path, front_bytes, artist_bytes):
                updated += 1
            else:
                failed += 1

    print(f"\n{'=' * 60}")
    print(f"Done. Updated: {updated}   Already correct: {skipped}   Failed: {failed}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else input(
        "Enter folder path (or '.' for current directory): "
    ).strip() or "."
    process_library(target)