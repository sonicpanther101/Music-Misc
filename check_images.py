"""
Enhanced FLAC Image Manager
Checks FLAC files for album covers and artist images, fixes oversized images,
and fetches high-resolution album covers from Last.fm.
Changes are grouped and applied by album.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from mutagen.flac import FLAC, Picture
from PIL import Image
import warnings
from io import BytesIO
import requests
from bs4 import BeautifulSoup

# Suppress PIL warnings about corrupt EXIF data
warnings.filterwarnings('ignore', category=UserWarning, module='PIL')

# === CONFIG ===
MAX_IMAGE_SIZE_MB = 2
MIN_COVER_RESOLUTION = 600
TARGET_QUALITY = 85
CACHE_DIR = "image_cache"

# === SETUP ===
os.makedirs(CACHE_DIR, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def check_ffmpeg():
    """Check if ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def resize_image_ffmpeg(image_data, max_size_mb=MAX_IMAGE_SIZE_MB):
    """Use ffmpeg to compress/resize image to target file size."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as input_file:
        input_file.write(image_data)
        input_path = input_file.name
    
    output_path = input_path.replace(".jpg", "_compressed.jpg")
    
    try:
        # Try progressive quality reduction
        for quality in [85, 75, 65, 55, 45]:
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-q:v", str(quality),
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            
            output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            if output_size_mb <= max_size_mb:
                with open(output_path, "rb") as f:
                    compressed_data = f.read()
                os.unlink(input_path)
                os.unlink(output_path)
                return compressed_data, output_size_mb
        
        # If still too large, resize dimensions
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", "scale='min(1200,iw)':'min(1200,ih)':force_original_aspect_ratio=decrease",
            "-q:v", "75",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        
        with open(output_path, "rb") as f:
            compressed_data = f.read()
        
        output_size_mb = len(compressed_data) / (1024 * 1024)
        os.unlink(input_path)
        os.unlink(output_path)
        return compressed_data, output_size_mb
        
    except Exception as e:
        print(f"Error during ffmpeg compression: {e}")
        if os.path.exists(input_path):
            os.unlink(input_path)
        if os.path.exists(output_path):
            os.unlink(output_path)
        return None, 0


def scrape_lastfm_album_images(artist_name, album_name):
    """Scrape high-resolution album cover images from Last.fm."""
    artist_url = artist_name.replace(" ", "+")
    album_url = album_name.replace(" ", "+")
    url = f"https://www.last.fm/music/{artist_url}/{album_url}/+images"
    
    print(f"  Fetching from: {url}")
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.content, 'html.parser')
        images = []
        
        img_tags = soup.find_all('img')
        
        for img in img_tags:
            src = img.get('src', '')
            
            if 'lastfm.freetls.fastly.net' in src or 'last.fm' in src:
                high_res = src.replace('/avatar170s/', '/300x300/')
                high_res = high_res.replace('/50s/', '/300x300/')
                high_res = high_res.replace('/64s/', '/300x300/')
                high_res = high_res.replace('/avatar/', '/300x300/')
                high_res = high_res.replace('/300x300/', '/770x0/')
                
                if high_res not in images and 'default_' not in high_res:
                    images.append(high_res)
        
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        
        return unique_images
        
    except Exception as e:
        print(f"  Error scraping Last.fm: {e}")
        return []


def download_image(url):
    """Download image from URL."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"  Error downloading image: {e}")
        return None


def check_and_fix_flac_images(folder_path, auto_fix=False, fetch_covers=False):
    """Check all FLAC files in a folder and optionally fix issues."""
    
    folder = Path(folder_path)
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist.")
        return
    
    flac_files = list(folder.glob("*.flac"))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder_path}'")
        return
    
    has_ffmpeg = check_ffmpeg()
    if not has_ffmpeg and auto_fix:
        print("Warning: ffmpeg not found. Image compression will be skipped.")
    
    # Group files by album
    albums = {}
    for flac_path in flac_files:
        try:
            audio = FLAC(flac_path)
            album_artist = audio.get("albumartist", [None])[0] or audio.get("artist", [None])[0]
            album_name = audio.get("album", [None])[0]
            
            if not album_artist:
                album_artist = "Unknown Artist"
            if not album_name:
                album_name = "Unknown Album"
            
            album_key = (album_artist, album_name)
            if album_key not in albums:
                albums[album_key] = []
            albums[album_key].append(flac_path)
        except Exception as e:
            print(f"Error reading {flac_path.name}: {e}")
    
    # Analyze all albums and collect issues
    album_analysis = {}
    
    for album_key, flac_paths in albums.items():
        album_artist, album_name = album_key
        
        needs_cover = False
        needs_better_cover = False
        has_oversized = False
        
        file_details = []
        
        for flac_path in flac_paths:
            file_info = {
                'path': flac_path,
                'issues': [],
                'has_cover': False,
                'cover_low_res': False,
                'oversized_images': []
            }
            
            try:
                audio = FLAC(flac_path)
                pictures = audio.pictures
                
                if not pictures:
                    file_info['issues'].append("No embedded images")
                    needs_cover = True
                else:
                    for pic in pictures:
                        pic_size_mb = len(pic.data) / (1024 * 1024)
                        
                        # Check for cover images
                        if pic.type in [0, 3, 4]:
                            file_info['has_cover'] = True
                            
                            # Check resolution
                            try:
                                img = Image.open(BytesIO(pic.data))
                                width, height = img.size
                                
                                if width < MIN_COVER_RESOLUTION or height < MIN_COVER_RESOLUTION:
                                    file_info['issues'].append(f"Low resolution cover: {width}x{height}")
                                    file_info['cover_low_res'] = True
                                    needs_better_cover = True
                            except Exception as e:
                                file_info['issues'].append("Unable to read cover resolution")
                            
                            # Check size
                            if pic_size_mb > MAX_IMAGE_SIZE_MB:
                                file_info['issues'].append(f"Oversized cover: {pic_size_mb:.2f} MB")
                                file_info['oversized_images'].append(('cover', pic_size_mb))
                                has_oversized = True
                        
                        # Check artist images
                        elif pic.type == 8:
                            if pic_size_mb > MAX_IMAGE_SIZE_MB:
                                file_info['issues'].append(f"Oversized artist image: {pic_size_mb:.2f} MB")
                                file_info['oversized_images'].append(('artist', pic_size_mb))
                                has_oversized = True
                    
                    if not file_info['has_cover']:
                        file_info['issues'].append("Missing album cover")
                        needs_cover = True
            
            except Exception as e:
                file_info['issues'].append(f"Error: {e}")
            
            file_details.append(file_info)
        
        # Store album analysis
        if needs_cover or needs_better_cover or has_oversized:
            album_analysis[album_key] = {
                'artist': album_artist,
                'album': album_name,
                'files': file_details,
                'needs_cover': needs_cover,
                'needs_better_cover': needs_better_cover,
                'has_oversized': has_oversized,
                'file_count': len(flac_paths)
            }
    
    # Display results
    if not album_analysis:
        print("\n✓ All FLAC files passed checks")
        return
    
    print("\n" + "="*60)
    print("ISSUES FOUND (grouped by album):")
    print("="*60)
    
    for album_key, data in album_analysis.items():
        print(f"\n📀 {data['artist']} - {data['album']}")
        print(f"   ({data['file_count']} file(s))")
        
        # Summary of album-wide issues
        issues_summary = []
        if data['needs_cover']:
            issues_summary.append("Missing covers")
        if data['needs_better_cover']:
            issues_summary.append("Low resolution covers")
        if data['has_oversized']:
            issues_summary.append("Oversized images")
        
        if issues_summary:
            print(f"   Issues: {', '.join(issues_summary)}")
        
        # Show individual file issues
        for file_info in data['files']:
            if file_info['issues']:
                print(f"   • {file_info['path'].name}")
                for issue in file_info['issues']:
                    print(f"     - {issue}")
    
    # Apply fixes if requested
    if not auto_fix:
        print(f"\n{len(album_analysis)} album(s) with issues found.")
        print("Run with auto-fix option to apply fixes.")
        return
    
    print("\n" + "="*60)
    print("APPLYING FIXES (album by album):")
    print("="*60)
    
    albums_fixed = 0
    files_fixed = 0
    
    for album_key, data in album_analysis.items():
        print(f"\n{'='*60}")
        print(f"📀 {data['artist']} - {data['album']}")
        print(f"   {data['file_count']} file(s)")
        print("="*60)
        
        # Show what will be fixed
        fixes_to_apply = []
        if data['needs_cover'] or data['needs_better_cover']:
            if fetch_covers:
                if data['needs_cover']:
                    fixes_to_apply.append("Fetch and add album covers")
                else:
                    fixes_to_apply.append("Replace with higher resolution covers")
        
        if data['has_oversized']:
            fixes_to_apply.append("Compress oversized images")
        
        if fixes_to_apply:
            print("\n  Proposed fixes for this album:")
            for fix in fixes_to_apply:
                print(f"   • {fix}")
            
            response = input(f"\n  Apply these fixes to all {data['file_count']} files? [y/N/q(quit)]: ").strip().lower()
            
            if response == 'q':
                print("\nQuitting fixes.")
                return
            
            if response != 'y':
                print("  Skipped this album.")
                continue
            
            # User approved - apply fixes to all files in album
            album_cover_data = None
            
            # Fetch album cover if needed
            if (data['needs_cover'] or data['needs_better_cover']) and fetch_covers:
                print(f"\n  Fetching album cover from Last.fm...")
                images = scrape_lastfm_album_images(data['artist'], data['album'])
                
                if images:
                    album_cover_data = download_image(images[0])
                    if album_cover_data:
                        print(f"  ✓ Album cover downloaded")
                    else:
                        print(f"  ✗ Failed to download image")
                else:
                    print(f"  ✗ No images found on Last.fm")
            
            # Apply fixes to each file in the album
            album_modified = False
            
            for file_info in data['files']:
                flac_path = file_info['path']
                
                try:
                    audio = FLAC(flac_path)
                    pictures = list(audio.pictures)
                    file_modified = False
                    
                    # Add or replace album cover
                    if album_cover_data:
                        if not file_info['has_cover']:
                            pic = Picture()
                            pic.type = 3
                            pic.mime = "image/jpeg"
                            pic.data = album_cover_data
                            pictures.append(pic)
                            file_modified = True
                            print(f"  ✓ {flac_path.name}: Added album cover")
                        elif file_info['cover_low_res']:
                            for i, pic in enumerate(pictures):
                                if pic.type in [0, 3, 4]:
                                    pictures[i].data = album_cover_data
                                    pictures[i].mime = "image/jpeg"
                                    file_modified = True
                                    print(f"  ✓ {flac_path.name}: Replaced cover with higher resolution")
                                    break
                    
                    # Compress oversized images
                    if file_info['oversized_images'] and has_ffmpeg:
                        for i, pic in enumerate(pictures):
                            pic_size_mb = len(pic.data) / (1024 * 1024)
                            
                            if pic_size_mb > MAX_IMAGE_SIZE_MB:
                                compressed_data, new_size = resize_image_ffmpeg(pic.data, MAX_IMAGE_SIZE_MB)
                                
                                if compressed_data:
                                    pictures[i].data = compressed_data
                                    file_modified = True
                                    print(f"  ✓ {flac_path.name}: Compressed image ({pic_size_mb:.2f} MB → {new_size:.2f} MB)")
                    
                    # Save changes
                    if file_modified:
                        audio.clear_pictures()
                        for p in pictures:
                            audio.add_picture(p)
                        audio.save()
                        files_fixed += 1
                        album_modified = True
                
                except Exception as e:
                    print(f"  ✗ {flac_path.name}: Error - {e}")
            
            if album_modified:
                albums_fixed += 1
                print(f"\n  ✓ Album '{data['album']}' updated successfully")
    
    if albums_fixed > 0:
        print(f"\n{'='*60}")
        print(f"✓ Successfully fixed {files_fixed} file(s) across {albums_fixed} album(s)")
    else:
        print(f"\nNo changes were made.")

def main(path=None):
    """Main entry point."""
    if path:
        folder = path
    else:
        folder = input("Enter folder path (or press Enter for current directory): ").strip()
        if not folder:
            folder = "."
    
    print("\nOptions:")
    print("1. Check only")
    print("2. Check and auto-fix (compress oversized images)")
    print("3. Check, fix, and fetch missing album covers from Last.fm")
    
    choice = input("\nSelect option [1-3]: ").strip()
    
    auto_fix = choice in ["2", "3"]
    fetch_covers = choice == "3"
    
    check_and_fix_flac_images(folder, auto_fix=auto_fix, fetch_covers=fetch_covers)


if __name__ == "__main__":
    main("C:/Users/Adam/Music/New unformated songs")