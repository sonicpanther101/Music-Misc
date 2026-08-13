import os
import re
import random
import time
import readline
import urllib.parse
from io import BytesIO
from bs4 import BeautifulSoup
import matplotlib

matplotlib.use("GTK3Agg")  # or 'Qt5Agg' if you have Qt installed
from matplotlib.image import imread
import matplotlib.pyplot as plt
from mutagen.flac import FLAC, Picture

# curl_cffi impersonates a real browser's TLS/HTTP2 fingerprint.
# `requests`/urllib3 has a distinctive fingerprint that Last.fm's edge
# (Cloudflare-style bot protection) flags and rejects with 406, no matter
# what headers you send. curl_cffi's Session API is requests-compatible.
#
#   pip install curl_cffi
#
from curl_cffi import requests

# === CONFIG ===
RECURSIVE = True
CACHE_DIR = "artist_previews"
ADD_IMAGE_URL_TAG = False  # add ARTISTIMAGEURL tag
IMPERSONATE = "chrome124"  # which browser fingerprint to mimic
MIN_DELAY = 1.5            # seconds between artist requests (be polite)
MAX_DELAY = 3.5
MAX_RETRIES = 3

# === SETUP ===
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.last.fm/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

# Persistent session with browser-like TLS fingerprint + cookie jar
session = requests.Session(impersonate=IMPERSONATE)
session.headers.update(HEADERS)

_warmed_up = False


def warm_up_session():
    """Hit the homepage first so we pick up normal session cookies,
    the same way a real browser would before navigating to an artist page."""
    global _warmed_up
    if _warmed_up:
        return
    try:
        session.get("https://www.last.fm/", timeout=10)
        _warmed_up = True
    except Exception as e:
        print(f"Warm-up request failed (continuing anyway): {e}")


# Global figure for image display
fig = None
ax = None


def init_matplotlib():
    """Initialize matplotlib figure once."""
    global fig, ax
    plt.ion()  # Interactive mode
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.canvas.manager.set_window_title("Artist Image Preview")


def show_image(fname, artist_name, img_num, total):
    """Display image in the same matplotlib window."""
    global fig, ax
    if fig is None:
        init_matplotlib()

    try:
        ax.clear()
        img = imread(fname)
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(
            f"{artist_name} - Image {img_num}/{total}", fontsize=14, pad=10
        )
        fig.tight_layout()
        plt.draw()
        plt.pause(0.1)
    except Exception as e:
        print(f"Could not preview image: {e}")


def close_matplotlib():
    """Close the matplotlib window."""
    global fig
    if fig is not None:
        plt.close(fig)
        fig = None


def find_flacs(folder):
    flac_files = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(".flac"):
                flac_files.append(os.path.join(root, file))
        if not RECURSIVE:
            break
    return flac_files


def group_by_album_artist(flac_files):
    """Group FLACs by ALBUMARTIST (fallback to ARTIST)."""
    artists = {}
    for path in flac_files:
        try:
            audio = FLAC(path)
            album_artist = audio.get("albumartist", [None])[0]
            key = album_artist or audio.get("artist", ["Unknown Artist"])[0]
            artists.setdefault(key, []).append(path)
        except Exception as e:
            print(f"Error reading {path}: {e}")
    return artists


def has_artist_image(flac_path):
    """Check if FLAC already has artist image (picture type = 8)."""
    try:
        audio = FLAC(flac_path)
        for pic in audio.pictures:
            if pic.type == 8:
                return True
    except Exception:
        pass
    return False


def extract_existing_artist_image(flac_paths):
    """If any FLAC already has artist image, return its data + URL tag (if any)."""
    for path in flac_paths:
        try:
            audio = FLAC(path)
            for pic in audio.pictures:
                if pic.type == 8:
                    url = audio.get("ARTISTIMAGEURL", [None])[0]
                    return pic.data, url
        except Exception:
            continue
    return None, None


def download_and_cache_image(url, artist_name, index):
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", artist_name)
    fname = os.path.join(CACHE_DIR, f"{safe_name}_{index}.jpg")
    if os.path.exists(fname):
        return fname
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        with open(fname, "wb") as f:
            f.write(r.content)
        return fname
    except Exception as e:
        print(f"Could not download image from {url}: {e}")
        return None


def _get_with_retries(url, timeout=10):
    """GET with retries + backoff, since 406/403 can be transient
    (rate limiting) even with a good TLS fingerprint."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code in (403, 406, 429):
                wait = attempt * 2 + random.uniform(0, 1.5)
                print(
                    f"Got {r.status_code}, retrying in {wait:.1f}s"
                    f" (attempt {attempt}/{MAX_RETRIES})..."
                )
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            wait = attempt * 2 + random.uniform(0, 1.5)
            time.sleep(wait)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts")


def scrape_lastfm_artist_images(artist_name):
    """Scrape artist images from Last.fm +images page."""
    warm_up_session()

    # Properly encode artist name for URL path
    artist_url = urllib.parse.quote_plus(artist_name)
    url = f"https://www.last.fm/music/{artist_url}/+images"

    print(f"Fetching: {url}")

    try:
        r = _get_with_retries(url, timeout=10)

        soup = BeautifulSoup(r.content, "html.parser")
        images = []

        # Remove 'similar artists' section to avoid grabbing wrong images
        for similar_section in soup.find_all(
            ["section", "div"], class_=re.compile(r"similar-")
        ):
            similar_section.decompose()

        # Find image tags in gallery
        img_tags = soup.find_all("img")

        for img in img_tags:
            src = img.get("src", "")

            if "lastfm.freetls.fastly.net" in src or "last.fm" in src:
                # Upgrade thumbnail URLs to maximum available resolution (770x0)
                high_res = re.sub(
                    r"/(avatar170s|50s|64s|300x300|avatar)/", "/770x0/", src
                )

                if high_res not in images and "default_" not in high_res:
                    images.append(high_res)
                    print(f"Found image: {high_res[:80]}...")

        # Preserve order while removing duplicates
        seen = set()
        unique_images = [
            img for img in images if not (img in seen or seen.add(img))
        ]
        return unique_images

    except Exception as e:
        print(f"Error scraping Last.fm: {e}")
        return []
    finally:
        # Be polite / avoid tripping rate limits between artists
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def choose_artist_image(artist_name, current, total):
    """Scrape Last.fm artist images and allow cycling through them."""
    print(f"\n[{current}/{total}] --- Artist: {artist_name} ---")

    images = scrape_lastfm_artist_images(artist_name)

    if not images:
        print("No images found on Last.fm.")
        return None, None

    print(f"Found {len(images)} images")

    idx = 0
    while idx < len(images):
        url = images[idx]
        print(f"\n→ Showing image {idx + 1}/{len(images)} for {artist_name}")
        print(f"   URL: {url[:80]}...")

        cached = download_and_cache_image(url, artist_name, idx + 1)

        if cached:
            show_image(cached, artist_name, idx + 1, len(images))
            choice = (
                input(
                    "Use this image? [y]es / [n]ext / [p]revious / [s]kip"
                    " artist: "
                )
                .strip()
                .lower()
            )

            if choice == "y":
                return cached, url
            elif choice == "n":
                idx += 1
            elif choice == "p":
                idx = max(0, idx - 1)
            elif choice == "s":
                return None, None
            else:
                idx += 1
        else:
            print("Could not preview this image, trying next...")
            idx += 1

    print("No more images available.")
    return None, None


def embed_artist_image(flac_paths, image_bytes, image_url, check_needed=True):
    if check_needed:
        confirm = (
            input(f"Embed artist image into {len(flac_paths)} FLACs? [y/N]: ")
            .strip()
            .lower()
        )
        if confirm != "y":
            print("Skipped embedding.")
            return

    for path in flac_paths:
        if has_artist_image(path):
            continue

        try:
            audio = FLAC(path)
            existing_pics = list(audio.pictures)

            # Create artist picture block (Type 8 = Artist/Performer)
            artist_pic = Picture()
            artist_pic.type = 8
            artist_pic.mime = "image/jpeg"
            artist_pic.data = image_bytes

            existing_pics.append(artist_pic)
            audio.clear_pictures()
            for p in existing_pics:
                audio.add_picture(p)

            if ADD_IMAGE_URL_TAG and image_url:
                audio["ARTISTIMAGEURL"] = image_url

            audio.save()
            print(f"✓ Updated {os.path.basename(path)}")
        except Exception as e:
            print(f"✗ Failed {path}: {e}")


def get_artist_image(Folder=None):
    if not Folder:
        folder = input("Enter folder path: ").strip()
        if not os.path.isdir(folder):
            print("Invalid folder.")
            return
    else:
        folder = Folder

    print("Scanning for FLAC files...")
    flac_files = find_flacs(folder)
    if not flac_files:
        print("No FLAC files found.")
        return
    print(f"Found {len(flac_files)} FLACs.")

    artists = group_by_album_artist(flac_files)
    total_artists = len(artists)

    try:
        for index, (artist, flacs) in enumerate(artists.items(), 1):
            existing_image, existing_url = extract_existing_artist_image(flacs)
            if existing_image:
                print(
                    f"[{index}/{total_artists}] Artist {artist}: already has"
                    " image, applying to others…"
                )
                embed_artist_image(flacs, existing_image, existing_url, False)
                continue

            image_path, image_url = choose_artist_image(
                artist, index, total_artists
            )
            if image_path:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                embed_artist_image(flacs, image_bytes, image_url)
            else:
                print(f"No image used for {artist}.")
    finally:
        close_matplotlib()


if __name__ == "__main__":
    get_artist_image("/home/adam/driveBig/Music/My Playlist")