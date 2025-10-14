import os
import requests
from mutagen.flac import FLAC, Picture
from PIL import Image
from io import BytesIO
import discogs_client

# === CONFIG ===
DISCOGS_TOKEN = "MUjfKKirKbaTLgdVCUhrgciLdCOsESEIMuePObiV"
RECURSIVE = True
CACHE_DIR = "artist_previews"
ADD_IMAGE_URL_TAG = False  # add ARTISTIMAGEURL tag

# === SETUP ===
os.makedirs(CACHE_DIR, exist_ok=True)
HEADERS = {"User-Agent": "DiscogsFlacTool/3.0 (https://discogs.com)"}


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
            artist = audio.get("artist", ["Unknown Artist"])[0]
            key = album_artist or artist or "Unknown Artist"
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
    safe_name = artist_name.replace("/", "_").replace("\\", "_")
    fname = os.path.join(CACHE_DIR, f"{safe_name}_{index}.jpg")
    if os.path.exists(fname):
        return fname
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        with open(fname, "wb") as f:
            f.write(r.content)
        return fname
    except Exception as e:
        print(f"Could not download image: {e}")
        return None


def show_image(fname):
    try:
        img = Image.open(fname)
        img.show()
    except Exception as e:
        print(f"Could not preview image: {e}")


def choose_artist_image(discogs, artist_name, current, total):
    """Search Discogs for this artist and prompt user interactively."""
    print(f"\n[{current}/{total}] --- Artist: {artist_name} ---")
    try:
        results = discogs.search(artist_name, type="artist")
        for i, artist in enumerate(results.page(1), 1):
            print(f"\nResult {i}: {artist.name}")
            print(f"Discogs URL: {artist.url}")
            if artist.images:
                for j, img in enumerate(artist.images, 1):
                    url = img.get("uri")
                    print(f"→ Showing image {j}/{len(artist.images)} for {artist.name}")
                    cached = download_and_cache_image(url, artist_name, j)
                    if cached:
                        show_image(cached)
                        choice = input("Use this image? [y]es / [n]ext / [s]kip artist: ").strip().lower()
                        if choice == "y":
                            return cached, url
                        elif choice == "s":
                            return None, None
                    else:
                        print("No image preview available.")
            else:
                print("No images found.")
    except Exception as e:
        print(f"Discogs search failed for {artist_name}: {e}")
    return None, None


def embed_artist_image(flac_paths, image_bytes, image_url, check_needed=True):
    if check_needed:
        confirm = input(f"Embed artist image into {len(flac_paths)} FLACs? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Skipped embedding.")
            return

    for path in flac_paths:
        if has_artist_image(path):
            print(f"↷ Skipped (already has artist image): {os.path.basename(path)}")
            continue

        try:
            audio = FLAC(path)
            pic = Picture()
            pic.type = 8  # artist/performer
            pic.mime = "image/jpeg"
            pic.data = image_bytes
            audio.add_picture(pic)
            if ADD_IMAGE_URL_TAG and image_url:
                audio["ARTISTIMAGEURL"] = [image_url]
            audio.save()
            print(f"✓ Updated {os.path.basename(path)}")
        except Exception as e:
            print(f"✗ Failed {path}: {e}")


def get_artist_image(Folder):
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
    discogs = discogs_client.Client("FlacArtistImageApp/3.0", user_token=DISCOGS_TOKEN)

    for index, (artist, flacs) in enumerate(artists.items(), 1):
        # First, check if any file already has an artist image
        existing_image, existing_url = extract_existing_artist_image(flacs)
        if existing_image:
            print(f"[{index}/{total_artists}] Artist {artist}: already has image, applying to others…")
            embed_artist_image(flacs, existing_image, existing_url, False)
            continue

        # If none have one, proceed to prompt user
        image_path, image_url = choose_artist_image(discogs, artist, index, total_artists)
        if image_path:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            embed_artist_image(flacs, image_bytes, image_url)
        else:
            print(f"No image used for {artist}.")


if __name__ == "__main__":
    get_artist_image("D:/Music/My Playlist")