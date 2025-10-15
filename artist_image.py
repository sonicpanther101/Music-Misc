import os
import requests
from mutagen.flac import FLAC, Picture
import matplotlib.pyplot as plt
from matplotlib.image import imread
from io import BytesIO
from bs4 import BeautifulSoup
import re

# === CONFIG ===
RECURSIVE = True
CACHE_DIR = "artist_previews"
ADD_IMAGE_URL_TAG = False  # add ARTISTIMAGEURL tag

# === SETUP ===
os.makedirs(CACHE_DIR, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

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
        ax.axis('off')
        ax.set_title(f"{artist_name} - Image {img_num}/{total}", fontsize=14, pad=10)
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
            key = album_artist or "Unknown Artist"
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
    safe_name = artist_name.replace("/", "_").replace("\\", "_").replace(":", "_")
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
        print(f"Could not download image from {url}: {e}")
        return None


def scrape_lastfm_artist_images(artist_name):
    """Scrape artist images from Last.fm +images page."""
    # Format artist name for URL
    artist_url = artist_name.replace(" ", "+")
    url = f"https://www.last.fm/music/{artist_url}/+images"
    
    print(f"Fetching: {url}")
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.content, 'html.parser')
        
        images = []
        
        # Exclude similar artists sections
        for similar_section in soup.find_all(['section', 'div'], class_=re.compile(r'similar-')):
            similar_section.decompose()
        
        # Find all image containers in the gallery
        # Last.fm uses img tags within the image gallery
        img_tags = soup.find_all('img')
        
        for img in img_tags:
            # Skip if image is within similar artists sections
            parent_classes = ' '.join(img.parent.get('class', []) if img.parent else [])
            if 'similar-' in parent_classes:
                continue
            
            # Get the src attribute
            src = img.get('src', '')
            
            # Filter for actual artist images (not icons, avatars, etc.)
            # Last.fm artist images typically have specific patterns
            if 'lastfm.freetls.fastly.net' in src or 'last.fm' in src:
                # Try to get higher resolution version
                # Replace size parameters to get larger images
                high_res = src.replace('/avatar170s/', '/300x300/')
                high_res = high_res.replace('/50s/', '/300x300/')
                high_res = high_res.replace('/64s/', '/300x300/')
                high_res = high_res.replace('/avatar/', '/300x300/')
                
                if high_res not in images and 'default_' not in high_res:
                    images.append(high_res)
                    print(f"Found image: {high_res[:80]}...")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        
        return unique_images
        
    except Exception as e:
        print(f"Error scraping Last.fm: {e}")
        return []


def choose_artist_image(artist_name, current, total):
    """Scrape Last.fm artist images and allow cycling through them."""
    print(f"\n[{current}/{total}] --- Artist: {artist_name} ---")
    
    images = scrape_lastfm_artist_images(artist_name)
    
    if not images:
        print("No images found on Last.fm.")
        return None, None
    
    print(f"Found {len(images)} images")
    
    # Cycle through images
    idx = 0
    while idx < len(images):
        url = images[idx]
        print(f"\n→ Showing image {idx + 1}/{len(images)} for {artist_name}")
        print(f"   URL: {url[:80]}...")
        
        cached = download_and_cache_image(url, artist_name, idx + 1)
        
        if cached:
            show_image(cached, artist_name, idx + 1, len(images))
            choice = input("Use this image? [y]es / [n]ext / [p]revious / [s]kip artist: ").strip().lower()
            
            if choice == "y":
                return cached, url
            elif choice == "n":
                idx += 1
                if idx >= len(images):
                    print("No more images available.")
                    return None, None
            elif choice == "p":
                idx = max(0, idx - 1)
            elif choice == "s":
                return None, None
            else:
                # Default to next
                idx += 1
                if idx >= len(images):
                    print("No more images available.")
                    return None, None
        else:
            print("Could not preview this image, trying next...")
            idx += 1
    
    print("No more images available.")
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
            # Keep existing pictures (covers, back, etc.)
            existing_pics = list(audio.pictures)

            # Create artist picture block
            artist_pic = Picture()
            artist_pic.type = 8  # artist/performer
            artist_pic.mime = "image/jpeg"
            artist_pic.data = image_bytes

            # Append without clearing
            existing_pics.append(artist_pic)
            audio.clear_pictures()
            for p in existing_pics:
                audio.add_picture(p)
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

    try:
        for index, (artist, flacs) in enumerate(artists.items(), 1):
            # First, check if any file already has an artist image
            existing_image, existing_url = extract_existing_artist_image(flacs)
            if existing_image:
                print(f"[{index}/{total_artists}] Artist {artist}: already has image, applying to others…")
                embed_artist_image(flacs, existing_image, existing_url, False)
                continue

            # If none have one, proceed to prompt user
            image_path, image_url = choose_artist_image(artist, index, total_artists)
            if image_path:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                embed_artist_image(flacs, image_bytes, image_url)
            else:
                print(f"No image used for {artist}.")
    finally:
        close_matplotlib()


if __name__ == "__main__":
    get_artist_image("D:/Music/My Playlist")