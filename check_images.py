import os
import subprocess
import requests
from mutagen.flac import FLAC, Picture
import matplotlib.pyplot as plt
from matplotlib.image import imread
from io import BytesIO
from bs4 import BeautifulSoup
from PIL import Image
from tqdm import tqdm

# === CONFIG ===
RECURSIVE = True
CACHE_DIR = "album_previews"
MIN_RESOLUTION = 600  # 600x600
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2MB

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
    fig.canvas.manager.set_window_title("Album Cover Preview")


def show_image(image_data, album_name, img_num=None, total=None):
    """Display image in the same matplotlib window."""
    global fig, ax
    if fig is None:
        init_matplotlib()
    
    try:
        ax.clear()
        img = Image.open(BytesIO(image_data))
        ax.imshow(img)
        ax.axis('off')
        
        title = f"{album_name}"
        if img_num and total:
            title += f" - Image {img_num}/{total}"
        title += f"\n{img.size[0]}x{img.size[1]} - {len(image_data)/1024:.1f}KB"
        
        ax.set_title(title, fontsize=12, pad=10)
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
    """Find all FLAC files in folder."""
    flac_files = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(".flac"):
                flac_files.append(os.path.join(root, file))
        if not RECURSIVE:
            break
    return flac_files


def group_by_album(flac_files):
    """Group FLACs by ALBUM and ALBUMARTIST."""
    albums = {}
    for path in flac_files:
        try:
            audio = FLAC(path)
            album = audio.get("album", [None])[0]
            album_artist = audio.get("albumartist", audio.get("artist", [None]))[0]
            
            if not album:
                album = "Unknown Album"
            if not album_artist:
                album_artist = "Unknown Artist"
            
            key = (album_artist, album)
            albums.setdefault(key, []).append(path)
        except Exception as e:
            print(f"Error reading {path}: {e}")
    return albums


def get_album_cover(flac_path):
    """Extract album cover from FLAC (type 3 = front cover)."""
    try:
        audio = FLAC(flac_path)
        for pic in audio.pictures:
            if pic.type == 3:  # Front cover
                return pic.data
    except Exception:
        pass
    return None


def check_cover_quality(image_data):
    """Check if cover meets minimum requirements.
    Returns (is_valid, width, height, size_bytes, issue)
    """
    try:
        img = Image.open(BytesIO(image_data))
        width, height = img.size
        size_bytes = len(image_data)
        
        issues = []
        if width < MIN_RESOLUTION or height < MIN_RESOLUTION:
            issues.append(f"resolution {width}x{height} < {MIN_RESOLUTION}x{MIN_RESOLUTION}")
        if size_bytes > MAX_SIZE_BYTES:
            issues.append(f"size {size_bytes/1024/1024:.2f}MB > 2MB")
        
        return len(issues) == 0, width, height, size_bytes, ", ".join(issues) if issues else None
    except Exception as e:
        return False, 0, 0, 0, f"Error: {e}"


def compress_image_ffmpeg(image_data, target_size_bytes):
    """Use ffmpeg to compress image below target size while preserving quality."""
    temp_input = os.path.join(CACHE_DIR, "temp_input.jpg")
    temp_output = os.path.join(CACHE_DIR, "temp_output.jpg")
    
    try:
        # Save input
        with open(temp_input, "wb") as f:
            f.write(image_data)
        
        # Get original image info
        img = Image.open(BytesIO(image_data))
        original_size = len(image_data)
        
        # Calculate target quality based on compression ratio needed
        compression_ratio = target_size_bytes / original_size
        
        # Start with high quality and use smaller steps
        if compression_ratio > 0.8:
            quality = 95
            step = 2
        elif compression_ratio > 0.6:
            quality = 90
            step = 3
        else:
            quality = 85
            step = 5
        
        best_result = None
        best_size = float('inf')
        
        while quality >= 70:
            cmd = [
                "ffmpeg", "-y", "-i", temp_input,
                "-q:v", str(int((100 - quality) / 3.125)),  # Convert to ffmpeg scale (2-31)
                temp_output
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            
            with open(temp_output, "rb") as f:
                compressed = f.read()
            
            compressed_size = len(compressed)
            print(f"   Trying quality {quality}: {compressed_size/1024:.1f}KB")
            
            # Keep track of best result that's under target
            if compressed_size <= target_size_bytes:
                if best_result is None or compressed_size > best_size:
                    best_result = compressed
                    best_size = compressed_size
                # If we're very close to target, use this
                if compressed_size > target_size_bytes * 0.9:
                    os.remove(temp_input)
                    os.remove(temp_output)
                    return best_result
            
            quality -= step
        
        # Return best result or None if nothing worked
        os.remove(temp_input)
        os.remove(temp_output)
        
        if best_result:
            return best_result
        else:
            print("   Could not compress to target size while maintaining quality")
            return None
        
    except Exception as e:
        print(f"FFmpeg compression failed: {e}")
        for f in [temp_input, temp_output]:
            if os.path.exists(f):
                os.remove(f)
        return None


def scrape_lastfm_album_images(artist_name, album_name):
    """Scrape album cover images from Last.fm album +images page."""
    artist_url = artist_name.replace(" ", "+").replace("/", r"%2F")
    album_url = album_name.replace(" ", "+")
    base_url = f"https://www.last.fm/music/{artist_url}/{album_url}/+images"
    
    print(f"Fetching: {base_url}")
    
    try:
        r = requests.get(base_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.content, 'html.parser')
        
        images = []
        
        # Find all image links in the gallery
        # Last.fm album pages use <a> tags linking to full image pages
        image_links = soup.find_all('a', href=True)
        
        for link in image_links:
            href = link.get('href', '')
            # Match pattern: /music/Artist/Album/+images/[hash]
            if '/+images/' in href and href.count('/') >= 5:
                # Construct full URL if relative
                if href.startswith('/'):
                    full_url = f"https://www.last.fm{href}"
                else:
                    full_url = href
                
                if full_url not in images:
                    images.append(full_url)
                    print(f"Found image page: {full_url}")
        
        # Now fetch actual image URLs from each image page
        actual_images = []
        for img_page_url in images[:10]:  # Limit to first 10
            try:
                r2 = requests.get(img_page_url, headers=HEADERS, timeout=10)
                r2.raise_for_status()
                soup2 = BeautifulSoup(r2.content, 'html.parser')
                
                # Find the actual image
                img_tags = soup2.find_all('img')
                for img in img_tags:
                    src = img.get('src', '')
                    if 'lastfm.freetls.fastly.net' in src or 'last.fm' in src:
                        # Get high resolution
                        high_res = src.replace('/avatar170s/', '/770x0/')
                        high_res = high_res.replace('/300x300/', '/770x0/')
                        high_res = high_res.replace('/64s/', '/770x0/')
                        
                        if 'default_' not in high_res and high_res not in actual_images:
                            actual_images.append(high_res)
                            print(f"  → Image URL: {high_res[:80]}...")
                            break
            except Exception as e:
                print(f"Could not fetch image page {img_page_url}: {e}")
        
        return actual_images
        
    except Exception as e:
        print(f"Error scraping Last.fm: {e}")
        return []


def download_image(url):
    """Download image and return bytes."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"Could not download image from {url}: {e}")
        return None


def choose_replacement_cover(artist_name, album_name):
    """Fetch and preview one Last.fm image at a time, only fetching next when requested."""
    print(f"\nSearching for album covers on Last.fm...")

    # Get list of image page URLs first (not image bytes)
    artist_url = artist_name.replace(" ", "+").replace("/", r"%2F")
    album_url = album_name.replace(" ", "+")
    base_url = f"https://www.last.fm/music/{artist_url}/{album_url}/+images"

    print(f"Fetching: {base_url}")
    try:
        r = requests.get(base_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching Last.fm page: {e}")
        return None

    soup = BeautifulSoup(r.content, 'html.parser')
    image_links = []
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/+images/' in href and href.count('/') >= 5:
            if href.startswith('/'):
                full_url = f"https://www.last.fm{href}"
            else:
                full_url = href
            if full_url not in image_links:
                image_links.append(full_url)

    if not image_links:
        print("No image pages found on Last.fm.")
        return None

    print(f"Found {len(image_links)} image pages on Last.fm.\n")

    idx = 0
    while 0 <= idx < len(image_links):
        img_page_url = image_links[idx]
        print(f"\n→ Fetching image {idx + 1}/{len(image_links)}")

        try:
            # Load actual image URL from the image page
            r2 = requests.get(img_page_url, headers=HEADERS, timeout=10)
            r2.raise_for_status()
            soup2 = BeautifulSoup(r2.content, 'html.parser')

            img_tag = None
            for img in soup2.find_all('img'):
                src = img.get('src', '')
                if 'lastfm.freetls.fastly.net' in src or 'last.fm' in src:
                    img_tag = src
                    break

            if not img_tag:
                print("No image found on this page.")
                idx += 1
                continue

            # Replace size with 770px if available
            high_res = img_tag.replace('/avatar170s/', '/770x0/')
            high_res = high_res.replace('/300x300/', '/770x0/')
            high_res = high_res.replace('/64s/', '/770x0/')

            image_data = download_image(high_res)
            if not image_data:
                print("Failed to download image.")
                idx += 1
                continue

            is_valid, w, h, size, issue = check_cover_quality(image_data)
            print(f"   Resolution: {w}x{h}, Size: {size/1024:.1f}KB")
            if is_valid:
                print("   ✓ Meets requirements")
            else:
                print(f"   ⚠ {issue}")

            show_image(image_data, f"{artist_name} - {album_name}", idx + 1, len(image_links))

            # User choice
            choice = input("Use this image? [y]es / [n]ext / [p]revious / [s]kip: ").strip().lower()

            if choice == "y":
                if not is_valid:
                    print(f"⚠ Warning: This image doesn't meet requirements ({issue})")
                    confirm = input("Use it anyway? [y/N]: ").strip().lower()
                    if confirm != "y":
                        continue
                return image_data
            elif choice == "n":
                idx += 1
            elif choice == "p":
                idx = max(0, idx - 1)
            elif choice == "s":
                return None
            else:
                print("Skipping...")
                idx += 1

        except Exception as e:
            print(f"Error processing image page: {e}")
            idx += 1

    print("No more images available.")
    return None


def update_album_covers(flac_paths, new_image_data):
    """Update album cover (type 3) in all FLACs."""
    for path in flac_paths:
        try:
            audio = FLAC(path)
            
            # Remove existing front covers (type 3)
            existing_pics = [p for p in audio.pictures if p.type != 3]
            
            # Create new front cover
            cover = Picture()
            cover.type = 3  # Front cover
            cover.mime = "image/jpeg"
            cover.data = new_image_data
            
            # Update pictures
            audio.clear_pictures()
            for p in existing_pics:
                audio.add_picture(p)
            audio.add_picture(cover)
            
            audio.save()
            print(f"✓ Updated {os.path.basename(path)}")
        except Exception as e:
            print(f"✗ Failed {path}: {e}")


def process_album_covers(folder=None):
    """Main function to check and fix album covers."""
    if not folder:
        folder = input("Enter folder path: ").strip()
        if not os.path.isdir(folder):
            print("Invalid folder.")
            return
    
    print("Scanning for FLAC files...")
    flac_files = find_flacs(folder)
    if not flac_files:
        print("No FLAC files found.")
        return
    print(f"Found {len(flac_files)} FLACs.")
    
    albums = group_by_album(flac_files)
    total_albums = len(albums)
    print(f"Found {total_albums} albums.\n")
    
    try:
        for index, ((artist, album), flacs) in enumerate(tqdm(albums.items(), total=len(albums), desc="Processing albums")):
            
            # Get cover from first file
            cover_data = get_album_cover(flacs[0])
            if not cover_data:
                print(f"\n{'='*60}")
                print(f"[{index}/{total_albums}] {artist} - {album}")
                print(f"{'='*60}")
                print(f"{len(flacs)} tracks")

                print("⚠ No album cover found!")
                choice = input("Search for cover on Last.fm? [y/N]: ").strip().lower()
                if choice == "y":
                    new_cover = choose_replacement_cover(artist, album)
                    if new_cover:
                        update_album_covers(flacs, new_cover)
                continue
            
            # Check quality
            is_valid, width, height, size, issue = check_cover_quality(cover_data)
            
            if is_valid:
                continue

            print(f"Current cover: {width}x{height}, {size/1024:.1f}KB")
            print(f"\n{'='*60}")
            print(f"[{index}/{total_albums}] {artist} - {album}")
            print(f"{'='*60}")
            print(f"{len(flacs)} tracks")
            
            print(f"✗ Issue: {issue}")
            show_image(cover_data, f"{artist} - {album}")
            
            # Determine action
            if size > MAX_SIZE_BYTES:
                print(f"\nCover is too large ({size/1024/1024:.2f}MB)")
                choice = input("Compress with ffmpeg? [Y/n]: ").strip().lower()
                if choice != "n":
                    print("Compressing...")
                    compressed = compress_image_ffmpeg(cover_data, MAX_SIZE_BYTES)
                    if compressed:
                        new_size = len(compressed)
                        print(f"✓ Compressed to {new_size/1024:.1f}KB")
                        update_album_covers(flacs, compressed)
                    else:
                        print("✗ Compression failed")
            
            if width < MIN_RESOLUTION or height < MIN_RESOLUTION:
                print(f"\nCover resolution too low ({width}x{height}) size: {size/1024:.1f}KB")
                choice = input("Search for better cover on Last.fm? [Y/n]: ").strip().lower()
                if choice != "n":
                    new_cover = choose_replacement_cover(artist, album)
                    if new_cover:
                        # Validate and fix new cover before applying
                        is_valid, w, h, s, issue = check_cover_quality(new_cover)
                        
                        # Check if it needs compression
                        if s > MAX_SIZE_BYTES:
                            print(f"New cover is too large ({s/1024/1024:.2f}MB), compressing...")
                            new_cover = compress_image_ffmpeg(new_cover, MAX_SIZE_BYTES)
                            if not new_cover:
                                print("✗ Compression failed, skipping album")
                                continue
                            # Recheck after compression
                            is_valid, w, h, s, issue = check_cover_quality(new_cover)
                        
                        # Final validation
                        if w >= MIN_RESOLUTION and h >= MIN_RESOLUTION and s <= MAX_SIZE_BYTES:
                            print(f"✓ New cover validated: {w}x{h}, {s/1024:.1f}KB")
                            update_album_covers(flacs, new_cover)
                        else:
                            print(f"✗ New cover still doesn't meet requirements: {issue}")
                            print("Skipping album")
    
    finally:
        close_matplotlib()
    
    print("\n" + "="*60)
    print("Processing complete!")


if __name__ == "__main__":
    process_album_covers("D:/Music/My Playlist")