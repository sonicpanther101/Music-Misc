#!/usr/bin/env python3
"""
FLAC Lyrics Tag Copier
Copies UNSYNCED LYRICS tag to LYRICS tag while keeping both tags
"""

import os
from pathlib import Path
from mutagen.flac import FLAC
from tqdm import tqdm

def copy_unsynced_to_lyrics(flac_file):
    """
    Copy UNSYNCED LYRICS tag to LYRICS tag in a FLAC file.
    
    Args:
        flac_file: Path to the FLAC file
    
    Returns:
        bool: True if lyrics were copied, False otherwise
    """
    try:
        audio = FLAC(flac_file)
        
        # Check if UNSYNCED LYRICS tag exists
        if 'UNSYNCED LYRICS' in audio:
            unsynced_lyrics = audio['UNSYNCED LYRICS']
            
            # Copy to LYRICS tag
            audio['LYRICS'] = unsynced_lyrics
            
            # Save the file
            audio.save()
            return True
        else:
            return False
            
    except Exception as e:
        print(f"Error processing {flac_file}: {e}")
        return False

def copy_lyrics(path=None):
    """
    Process all FLAC files in a folder.
    
    Args:
        path: Path to the folder containing FLAC files
    """
    
    print("FLAC Lyrics Tag Copier")
    print("=" * 50)
    print("This program copies UNSYNCED LYRICS tag to LYRICS tag")
    print("while keeping both tags intact.")
    print("=" * 50)
    print()
    
    if input('do you want to copy lyrics tags? ') != 'y':
        return
    
    if path:
        folder = Path(path)
    else:
        folder_path = input("Enter the folder path containing FLAC files: ").strip()
        # Remove quotes if present
        folder = Path(folder_path.strip('"').strip("'"))
    
    print()
    
    if not folder.exists():
        print(f"Error: Folder '{folder}' does not exist")
        return
    
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory")
        return
    
    # Find all FLAC files
    flac_files = list(folder.glob('*.flac'))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder}'")
        return
    
    print(f"Found {len(flac_files)} FLAC file(s)")
    print("-" * 50)
    
    processed = 0
    skipped = 0
    
    # Process files with progress bar
    for flac_file in tqdm(flac_files, desc="Processing FLAC files", unit="file"):
        if copy_unsynced_to_lyrics(flac_file):
            processed += 1
        else:
            tqdm.write(f"  ⊘ {flac_file.name}: No UNSYNCED LYRICS tag found, skipped")
            skipped += 1
    
    print("-" * 50)
    print(f"Summary: {processed} file(s) processed, {skipped} file(s) skipped")

if __name__ == "__main__":    
    copy_lyrics("/storage/emulated/0/Music/My Playlist")