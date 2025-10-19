import os
import sys
from pathlib import Path
from collections import defaultdict
from mutagen.flac import FLAC
from mutagen.flac import Picture
import io

def get_flac_files(folder_path):
    """Get all FLAC files in the specified folder."""
    flac_files = []
    for file in Path(folder_path).rglob("*.flac"):
        flac_files.append(str(file))
    return flac_files

def get_album_info_from_file(file_path):
    """Extract album name and artist from FLAC file metadata."""
    try:
        flac = FLAC(file_path)
        album = flac.get("album", ["Unknown"])[0]
        artist = flac.get("albumartist", flac.get("artist", ["Unknown"]))[0]
        return album, artist
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None, None

def get_picture_quality_score(picture):
    """Calculate quality score for an image (based on dimensions and file size)."""
    # Dimensions weighted more heavily than file size
    return picture.width * picture.height

def find_best_album_art(file_paths):
    """Find the best album art picture object across multiple files."""
    best_picture = None
    best_score = 0
    
    for file_path in file_paths:
        try:
            flac = FLAC(file_path)
            pictures = flac.pictures
            
            # Only consider pictures with type 3 (front cover)
            for pic in pictures:
                if pic.type == 3:  # type 3 is front cover
                    score = get_picture_quality_score(pic)
                    if score > best_score:
                        best_score = score
                        best_picture = pic
        except Exception as e:
            print(f"Error reading pictures from {file_path}: {e}")
    
    return best_picture

def update_flac_with_album_art(file_path, best_album_art):
    """Update FLAC file with the best album art while preserving other images."""
    try:
        flac = FLAC(file_path)
        
        # Keep existing pictures (covers, back, etc.)
        existing_pics = list(flac.pictures)
        
        existing_pics.append(best_album_art)
        flac.clear_pictures()
        for p in existing_pics:
            flac.add_picture(p)
        
        flac.save()
        return True
    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return False

def normalise_images(path=None):
    
    if not path:
        folder_path = input("Enter folder path (or '.' for current directory): ").strip()
        if not folder_path:
            folder_path = '.'
    else:
        folder_path = path
    
    if not os.path.isdir(folder_path):
        print(f"Error: {folder_path} is not a valid directory")
        sys.exit(1)
    
    # Get all FLAC files
    flac_files = get_flac_files(folder_path)
    
    if not flac_files:
        print("No FLAC files found in the specified folder.")
        sys.exit(0)
    
    print(f"Found {len(flac_files)} FLAC files")
    
    # Group files by album and artist
    albums = defaultdict(list)
    for file_path in flac_files:
        album, artist = get_album_info_from_file(file_path)
        if album and artist:
            # Use tuple of (album, artist) as key
            albums[(album, artist)].append(file_path)
    
    print(f"Found {len(albums)} albums\n")
    
    # Process each album
    updates_planned = []
    
    for (album_name, artist_name), files in sorted(albums.items()):
        if len(files) == 0:
            continue
        
        # Find best album art
        best_art = find_best_album_art(files)
        
        if best_art is None:
            print(f"Album: {album_name}")
            print(f"  Artist: {artist_name}")
            print(f"  Files: {len(files)}")
            print("  No front cover art found\n")
            continue
        
        size_mb = len(best_art.data) / (1024 * 1024)
        
        # Check which files need updating
        files_to_update = []
        for file_path in files:
            try:
                flac = FLAC(file_path)
                has_best_art = False
                for pic in flac.pictures:
                    if (pic.type == 3 and 
                        pic.width == best_art.width and 
                        pic.height == best_art.height and
                        pic.data == best_art.data):
                        has_best_art = True
                        break
                
                if not has_best_art:
                    files_to_update.append(file_path)
            except:
                files_to_update.append(file_path)
        
        if files_to_update:
            print(f"Album: {album_name}")
            print(f"  Artist: {artist_name}")
            print(f"  Files: {len(files)}")
            print(f"  Best art: {best_art.width}x{best_art.height} pixels ({size_mb:.2f} MB)")
            print(f"  Need to update: {len(files_to_update)} files")
            
            # Ask user for this specific album
            response = input(f"  Update this album? (yes/no): ").strip().lower()
            if response in ["yes", "y"]:
                updates_planned.append((album_name, artist_name, best_art, files_to_update))
                print("  ✓ Accepted")
            else:
                print("  ✗ Skipped")

            print()
    
    if not updates_planned:
        print("No updates accepted!")
        sys.exit(0)
    
    # Summary and final confirmation
    total_files_to_update = sum(len(files) for _, _, _, files in updates_planned)
    print(f"\n{'='*60}")
    print(f"Summary: {len(updates_planned)} albums, {total_files_to_update} files to update")
    print(f"{'='*60}\n")
    
    response = input("Apply all accepted updates? (yes/no): ").strip().lower()
    
    if response not in ["yes", "y"]:
        print("Cancelled.")
        sys.exit(0)
    
    # Apply updates
    success_count = 0
    for album_name, artist_name, best_art, files in updates_planned:
        print(f"Updating {album_name} by {artist_name}...")
        for file_path in files:
            if update_flac_with_album_art(file_path, best_art):
                success_count += 1
            else:
                print(f"  Failed: {os.path.basename(file_path)}")
    
    print(f"\n{'='*60}")
    print(f"Complete! Updated {success_count}/{total_files_to_update} files")
    print(f"{'='*60}")

if __name__ == "__main__":
    normalise_images("C:/Users/Adam/Music/My Playlist")