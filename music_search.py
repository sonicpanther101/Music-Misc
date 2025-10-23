#!/usr/bin/env python3
"""
Search for a string in FLAC file lyrics tags and display matching songs.
"""

import os
import sys
from pathlib import Path
from mutagen.flac import FLAC
import re
from tqdm import tqdm

def search_lyrics_in_flac(directory, search_string):
    """
    Search for a string in unsynced lyrics tags of FLAC files.
    
    Args:
        directory: Path to directory containing FLAC files
        search_string: String to search for in lyrics
    """
    directory = Path(directory)
    
    if not directory.exists():
        print(f"Error: Directory '{directory}' does not exist")
        return
    
    if not directory.is_dir():
        print(f"Error: '{directory}' is not a directory")
        return
    
    # Find all FLAC files recursively
    flac_files = list(directory.rglob("*.flac"))
    
    if not flac_files:
        print(f"No FLAC files found in '{directory}'")
        return
    
    print(f"Searching {len(flac_files)} FLAC files for '{search_string}'...\n")
    
    matches_found = 0
    search_lower = search_string.lower()
    
    for flac_path in tqdm(flac_files, desc="Searching files", unit="file"):
        try:
            audio = FLAC(flac_path)

            # Check for unsynced lyrics tag (LYRICS or UNSYNCEDLYRICS)
            lyrics = None
            if 'UNSYNCED LYRICS' in audio:
                lyrics = audio['UNSYNCED LYRICS'][0]
            elif 'LYRICS' in audio:
                lyrics = audio['LYRICS'][0]

            if lyrics:
                lines = lyrics.splitlines()
                matches = []
                for i, line in enumerate(lines):
                    if search_lower in line.lower():
                        matches.append(i)

                if matches:
                    matches_found += 1
                    title = audio.get('TITLE', ['Unknown Title'])[0]
                    artist = audio.get('ARTIST', ['Unknown Artist'])[0]
                    album = audio.get('ALBUM', ['Unknown Album'])[0]

                    print(f"Match #{matches_found}:")
                    print(f"  Title:  {title}")
                    print(f"  Artist: {artist}")
                    print(f"  Album:  {album}")
                    print(f"  File:   {flac_path}\n")

                    for m in matches:
                        start = max(0, m - 3)
                        end = min(len(lines), m + 4)

                        print("  ...")
                        for j in range(start, end):
                            line_to_print = lines[j]
                            if j == m:
                                # Highlight the search term (yellow bold)
                                line_to_print = re.sub(
                                    f"(?i)({re.escape(search_string)})",
                                    "\033[1;33m\\1\033[0m",
                                    line_to_print
                                )
                            print(f"  {line_to_print}")
                        print("  ...\n")

        except Exception as e:
            print(f"Error processing {flac_path}: {e}", file=sys.stderr)
    
    if matches_found == 0:
        print(f"No songs found containing '{search_string}' in their lyrics.")
    else:
        print(f"\nTotal matches: {matches_found}")


def main(path=None):
    
    if path:
        directory = path
    else:
        directory = input("Directory: ")
    search_string = input("Lyric: ")
    
    search_lyrics_in_flac(directory, search_string)


if __name__ == "__main__":
    main("C:/Users/Adam/Music/My Playlist")