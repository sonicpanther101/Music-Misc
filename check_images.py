#!/usr/bin/env python3
"""
FLAC Image Checker
Checks FLAC files for album covers and artist images, verifying resolution and file size.
"""

import os
import sys
from pathlib import Path
from mutagen.flac import FLAC, Picture
from PIL import Image
from io import BytesIO

def check_flac_images(folder_path):
    """Check all FLAC files in a folder for embedded images."""
    
    folder = Path(folder_path)
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist.")
        return
    
    flac_files = list(folder.glob("*.flac"))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder_path}'")
        return
    
    issues_found = False
    
    for flac_path in flac_files:
        file_issues = []
        
        try:
            audio = FLAC(flac_path)
            pictures = audio.pictures
            
            if not pictures:
                file_issues.append("No embedded images found")
            else:
                has_cover = False
                has_artist = False
                
                for pic in pictures:
                    pic_type = pic.type
                    pic_data = pic.data
                    pic_size_mb = len(pic_data) / (1024 * 1024)
                    
                    # Determine image type
                    # Type 3 = Front cover, Type 0 = Other (often used as cover), Type 4 = Back cover
                    if pic_type in [0, 3, 4]:  # Accept common cover types
                        img_type = "Album Cover"
                        has_cover = True
                        is_cover = True
                    elif pic_type == 8:  # Artist/Performer
                        img_type = "Artist Image"
                        has_artist = True
                        is_cover = False
                    else:
                        continue  # Skip other image types
                    
                    # Check file size
                    if pic_size_mb > 10:
                        file_issues.append(f"{img_type}: Size {pic_size_mb:.2f} MB (exceeds 2MB)")
                    
                    # Check resolution for album covers
                    if is_cover:
                        try:
                            img = Image.open(BytesIO(pic_data))
                            width, height = img.size
                            
                            if width < 600 or height < 600:
                                file_issues.append(f"{img_type}: Resolution {width}x{height} (below 600x600)")
                        except Exception as e:
                            file_issues.append(f"{img_type}: Unable to read resolution")
                
                # Check for missing images
                if not has_cover:
                    file_issues.append("Missing album cover")
                if not has_artist:
                    file_issues.append("Missing artist image")
            
        except Exception as e:
            file_issues.append(f"Error reading file: {e}")
        
        # Print only if there are issues
        if file_issues:
            if not issues_found:
                issues_found = True
            print(f"\n{flac_path.name}")
            for issue in file_issues:
                print(f"  ❌ {issue}")
    
    if not issues_found:
        print("All FLAC files passed checks ✓")

def check_images(path):
    if path:
        folder = path
    else:
        folder = input("Enter folder path (or press Enter for current directory): ").strip()
        if not folder:
            folder = "."
    
    check_flac_images(folder)

if __name__ == "__main__":
    check_images()