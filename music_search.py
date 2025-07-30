#!/usr/bin/env python3
"""
Music Metadata Search Tool for Android
Requires: pip install mutagen

Usage examples:
- Search lyrics: python music_search.py --lyrics "love"
- Search artist: python music_search.py --artist "Beatles"
- Search any field: python music_search.py --field "GENRE" --value "rock"
- List all songs: python music_search.py --list
"""

import os
import argparse
import re
from pathlib import Path
from mutagen import File
from mutagen.id3 import ID3NoHeaderError

class MusicSearcher:
    def __init__(self, music_dirs=None):
        if music_dirs is None:
            # Common Android music directories
            self.music_dirs = [
                "/storage/emulated/0/Music",
                "/storage/emulated/0/Download", 
                "/sdcard/Music",
                "/sdcard/Download",
                "/storage/emulated/0/Documents/Music/My Playlist"
            ]
        else:
            self.music_dirs = music_dirs
        
        self.supported_formats = {'.mp3', '.flac', '.ogg', '.m4a', '.mp4', '.wma'}
    
    def find_music_files(self):
        """Find all supported music files in the specified directories."""
        music_files = []
        
        for music_dir in self.music_dirs:
            if os.path.exists(music_dir):
                print(f"Scanning: {music_dir}")
                for root, dirs, files in os.walk(music_dir):
                    for file in files:
                        if Path(file).suffix.lower() in self.supported_formats:
                            full_path = os.path.join(root, file)
                            music_files.append(full_path)
        
        return music_files
    
    def get_metadata(self, file_path):
        """Extract metadata from a music file."""
        try:
            audio_file = File(file_path)
            if audio_file is None:
                return None
            
            metadata = {}
            
            # Common tags mapping
            tag_mappings = {
                'title': ['TIT2', 'TITLE', '\xa9nam'],
                'artist': ['TPE1', 'ARTIST', '\xa9ART'],
                'album': ['TALB', 'ALBUM', '\xa9alb'],
                'genre': ['TCON', 'GENRE', '\xa9gen'],
                'date': ['TDRC', 'DATE', '\xa9day'],
                'lyrics': ['USLT', 'LYRICS', '\xa9lyr', 'UNSYNCEDLYRICS', 'UNSYNCED LYRICS']
            }
            
            # Extract standard tags
            for field, possible_keys in tag_mappings.items():
                for key in possible_keys:
                    if key in audio_file:
                        value = audio_file[key]
                        if isinstance(value, list) and value:
                            # Handle USLT (lyrics) specially
                            if key == 'USLT' and hasattr(value[0], 'text'):
                                metadata[field] = value[0].text
                            else:
                                metadata[field] = str(value[0])
                        elif hasattr(value, 'text'):
                            metadata[field] = value.text
                        else:
                            metadata[field] = str(value)
                        break
            
            # Add file info
            metadata['file_path'] = file_path
            metadata['file_name'] = os.path.basename(file_path)
            
            return metadata
            
        except (ID3NoHeaderError, Exception) as e:
            print(f"Error reading {file_path}: {e}")
            return None
    
    def search_by_lyrics(self, query, case_sensitive=False):
        """Search for songs containing specific lyrics."""
        results = []
        music_files = self.find_music_files()
        
        print(f"Searching {len(music_files)} files for lyrics containing: '{query}'")
        
        for file_path in music_files:
            metadata = self.get_metadata(file_path)
            if metadata and 'lyrics' in metadata:
                lyrics = metadata['lyrics']
                if not case_sensitive:
                    lyrics = lyrics.lower()
                    query = query.lower()
                
                if query in lyrics:
                    results.append(metadata)
        
        return results
    
    def search_by_field(self, field, value, case_sensitive=False):
        """Search for songs by any metadata field."""
        results = []
        music_files = self.find_music_files()
        
        print(f"Searching {len(music_files)} files for {field} containing: '{value}'")
        
        for file_path in music_files:
            metadata = self.get_metadata(file_path)
            if metadata and field.lower() in metadata:
                field_value = str(metadata[field.lower()])
                if not case_sensitive:
                    field_value = field_value.lower()
                    value = value.lower()
                
                if value in field_value:
                    results.append(metadata)
        
        return results
    
    def list_all_songs(self):
        """List all songs with their metadata."""
        results = []
        music_files = self.find_music_files()
        
        print(f"Found {len(music_files)} music files")
        
        for file_path in music_files:
            metadata = self.get_metadata(file_path)
            if metadata:
                results.append(metadata)
        
        return results
    
    def print_results(self, results):
        """Print search results in a readable format."""
        if not results:
            print("No matches found.")
            return
        
        print(f"\nFound {len(results)} matches:\n")
        
        for i, song in enumerate(results, 1):
            print(f"{i}. {song.get('title', 'Unknown Title')}")
            print(f"   Artist: {song.get('artist', 'Unknown')}")
            print(f"   Album: {song.get('album', 'Unknown')}")
            print(f"   File: {song.get('file_name', '')}")
            
            if 'lyrics' in song and song['lyrics']:
                # Show first 100 characters of lyrics
                lyrics_preview = song['lyrics'][:100] + "..." if len(song['lyrics']) > 100 else song['lyrics']
                print(f"   Lyrics preview: {lyrics_preview}")
            
            print(f"   Path: {song.get('file_path', '')}")
            print()

def main():
    parser = argparse.ArgumentParser(description='Search music files by metadata')
    parser.add_argument('--lyrics', help='Search by lyrics content')
    parser.add_argument('--artist', help='Search by artist name')
    parser.add_argument('--title', help='Search by song title')
    parser.add_argument('--album', help='Search by album name')
    parser.add_argument('--genre', help='Search by genre')
    parser.add_argument('--field', help='Search by custom field name')
    parser.add_argument('--value', help='Value to search for (use with --field)')
    parser.add_argument('--case-sensitive', action='store_true', help='Case sensitive search')
    parser.add_argument('--list', action='store_true', help='List all songs')
    parser.add_argument('--dir', action='append', help='Additional directory to search')
    
    args = parser.parse_args()
    
    # Initialize searcher
    custom_dirs = args.dir if args.dir else None
    searcher = MusicSearcher(["/storage/emulated/0/Documents/Music"])
    
    results = []
    
    if args.list:
        results = searcher.list_all_songs()
    elif args.lyrics:
        results = searcher.search_by_lyrics(args.lyrics, args.case_sensitive)
    elif args.artist:
        results = searcher.search_by_field('artist', args.artist, args.case_sensitive)
    elif args.title:
        results = searcher.search_by_field('title', args.title, args.case_sensitive)
    elif args.album:
        results = searcher.search_by_field('album', args.album, args.case_sensitive)
    elif args.genre:
        results = searcher.search_by_field('genre', args.genre, args.case_sensitive)
    elif args.field and args.value:
        results = searcher.search_by_field(args.field, args.value, args.case_sensitive)
    else:
        print("Please specify a search parameter. Use --help for options.")
        return
    
    searcher.print_results(results)

if __name__ == "__main__":
    main()