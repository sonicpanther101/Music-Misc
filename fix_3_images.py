#!/usr/bin/env python3
"""
FLAC Cover Art Deduplicator
Analyzes FLAC files and removes duplicate front covers, keeping the highest quality one.
Preserves artist images and other picture types.
"""

import os
import readline
import sys
from pathlib import Path
from mutagen.flac import FLAC, Picture
from PIL import Image
from io import BytesIO

# Suppress PIL warnings about corrupt EXIF data
Image.warnings.filterwarnings('ignore', category=UserWarning, module='PIL')

def get_image_quality_score(pic):
    """Calculate quality score based on resolution and file size."""
    try:
        img = Image.open(BytesIO(pic.data))
        width, height = img.size
        resolution = width * height
        file_size = len(pic.data)
        
        # Score based on resolution (primary) and file size (secondary)
        score = resolution + (file_size / 1000)
        return score, width, height, file_size
    except Exception as e:
        print(f"  Error analyzing image: {e}")
        return 0, 0, 0, 0

def get_picture_type_name(pic_type):
    """Convert picture type number to readable name."""
    types = {
        0: "Other",
        1: "File icon",
        2: "Other file icon",
        3: "Front cover",
        4: "Back cover",
        5: "Leaflet page",
        6: "Media",
        7: "Lead artist/lead performer/soloist",
        8: "Artist/performer",
        9: "Conductor",
        10: "Band/Orchestra",
        11: "Composer",
        12: "Lyricist/text writer",
        13: "Recording Location",
        14: "During recording",
        15: "During performance",
        16: "Movie/video screen capture",
        17: "A bright coloured fish",
        18: "Illustration",
        19: "Band/artist logotype",
        20: "Publisher/Studio logotype"
    }
    return types.get(pic_type, f"Unknown ({pic_type})")

def process_flac_file(filepath):
    """Process a single FLAC file and deduplicate front covers."""
    try:
        audio = FLAC(filepath)
        
        if not audio.pictures:
            print(f"  No embedded images found")
            return False
        
        # Categorize pictures
        front_covers = []
        artist_images = []
        other_images = []
        
        for i, pic in enumerate(audio.pictures):
            pic_type_name = get_picture_type_name(pic.type)
            score, w, h, size = get_image_quality_score(pic)
            
            # Type 3 = Front cover
            if pic.type == 3:
                front_covers.append((i, pic, score, w, h, size))
            # Types 7-8 = Artist/performer images
            elif pic.type in [7, 8]:
                artist_images.append((i, pic))
            else:
                front_covers.append((i, pic, score, w, h, size))
            
        # check if song has type 3 image first in list
        ordered = True
        if audio.pictures[0].type != 3:
            ordered = False
            print(f"  Images are ordered incorrectly")
        
        # If we have multiple front covers, keep only the best one
        if len(front_covers) > 1 or len(other_images) > 0 or (not ordered):
            print(f"Processing: {filepath.name}")
            print(f"  Found {len(audio.pictures)} image(s)")
            for i, pic in enumerate(audio.pictures):
                pic_type_name = get_picture_type_name(pic.type)
                score, w, h, size = get_image_quality_score(pic)
                
                print(f"    [{i}] Type: {pic_type_name} | {w}x{h} | {size:,} bytes | Score: {score:,.0f}")
            print(f"\n  Found {len(front_covers)} front covers - keeping highest quality...")
            
            # Sort by quality score (descending)
            front_covers.sort(key=lambda x: x[2], reverse=True)
            best_cover = front_covers[0]
            
            print(f"  Keeping: {best_cover[3]}x{best_cover[4]} ({best_cover[5]:,} bytes)")
            for removed in front_covers[1:]:
                print(f"  Removing: {removed[3]}x{removed[4]} ({removed[5]:,} bytes)")

            if best_cover[1].type != 3:
                best_cover[1].type = 3
                print(f"  Changed {best_cover[1].type} to 3 (front cover)")
            
            # Rebuild pictures list with only the best front cover
            new_pictures = [best_cover[1]]
            new_pictures.extend([pic for _, pic in artist_images])
            # new_pictures.extend([pic for _, pic in other_images])

            # Sort by type
            new_pictures.sort(key=lambda x: x.type)
            
            # Clear and reassign pictures
            audio.clear_pictures()
            for pic in new_pictures:
                audio.add_picture(pic)
            
            audio.save()
            print(f"  ✓ Updated file with {len(new_pictures)} image(s)")
            
            print()
            return True
        else:
            return False
            
    except Exception as e:
        print(f"  ✗ Error processing file: {e}")
        return False

def fix_3_images(path=None):

    print("FLAC Cover Art Deduplicator")
    print("=" * 50)

    if input("Do you want to remove extra images from all FLAC files in a folder? (y/n): ").lower() != "y":
        print("Exiting...")
        return

    if path:
        folder_path = path
    else:
        folder_path = input("\nEnter the folder path containing FLAC files: ").strip()
    
    if not folder_path:
        print("Error: No folder path provided")
        sys.exit(1)
    
    print()

    """Process all FLAC files in a folder."""
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist")
        return
    
    if not folder.is_dir():
        print(f"Error: '{folder_path}' is not a directory")
        return
    
    flac_files = list(folder.glob("*.flac"))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder_path}'")
        return
    
    print(f"Found {len(flac_files)} FLAC file(s) in '{folder_path}'\n")
    
    modified_count = 0
    for flac_file in flac_files:
        if process_flac_file(flac_file):
            modified_count += 1
    
    print(f"Done! Modified {modified_count} file(s)")

if __name__ == "__main__":
    fix_3_images("/home/adam/driveBig/Music/My Playlist")