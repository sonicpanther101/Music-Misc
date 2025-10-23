#!/usr/bin/env python3
"""
FLAC Lyrics Tag Copier
Copies UNSYNCED LYRICS tag to LYRICS tag while keeping both tags
"""

import os
from pathlib import Path
from mutagen.flac import FLAC

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
        if 'UNSYNCEDLYRICS' in audio:
            unsynced_lyrics = audio['UNSYNCEDLYRICS'][0]
            
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

def process_folder(folder_path):
    """
    Process all FLAC files in a folder.
    
    Args:
        folder_path: Path to the folder containing FLAC files
    """
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist")
        return
    
    if not folder.is_dir():
        print(f"Error: '{folder_path}' is not a directory")
        return
    
    # Find all FLAC files
    flac_files = list(folder.glob('*.flac')) + list(folder.glob('*.FLAC'))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder_path}'")
        return
    
    print(f"Found {len(flac_files)} FLAC file(s)")
    print("-" * 50)
    
    processed = 0
    skipped = 0
    
    for flac_file in flac_files:
        print(f"Processing: {flac_file.name}")
        
        if copy_unsynced_to_lyrics(flac_file):
            print(f"  ✓ Copied UNSYNCED LYRICS to LYRICS")
            processed += 1
        else:
            print(f"  ⊘ No UNSYNCED LYRICS tag found, skipped")
            skipped += 1
    
    print("-" * 50)
    print(f"Summary: {processed} file(s) processed, {skipped} file(s) skipped")

def main():
    """Main function"""
    print("FLAC Lyrics Tag Copier")
    print("=" * 50)
    print("This program copies UNSYNCED LYRICS tag to LYRICS tag")
    print("while keeping both tags intact.")
    print("=" * 50)
    print()
    
    folder_path = input("Enter the folder path containing FLAC files: ").strip()
    
    # Remove quotes if present
    folder_path = folder_path.strip('"').strip("'")
    
    print()
    process_folder(folder_path)

if __name__ == "__main__":
    # Check if mutagen is installed
    try:
        import mutagen
    except ImportError:
        print("Error: mutagen library is not installed")
        print("Install it using: pip install mutagen")
        exit(1)
    
    main()