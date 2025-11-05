import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import time
import re
from mutagen.flac import FLAC

def get_artist_tracks_from_flacs(folder_path, target_artist):
    """Get all track titles from FLAC files by the specified artist using Mutagen."""
    tracks = set()
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist.")
        return []
    
    normalized_target = normalize_artist(target_artist)
    
    for file in folder.rglob("*.flac"):
        try:
            audio = FLAC(file)
            
            # Get artist from metadata
            artist = audio.get('albumartist', [''])[0]
            
            # Check if this file is by the target artist
            if normalize_artist(artist) == normalized_target:
                title = audio.get('title', [''])[0]
                if title:
                    tracks.add(normalize_track(title))
        except Exception as e:
            print(f"Error reading {file.name}: {e}")
    
    return tracks

def normalize_artist(artist):
    """Normalize artist name for comparison."""
    normalized = artist.lower()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized

def normalize_track(title):
    """Normalize track title - removes versions, live, explicit, features, etc."""
    # Convert to lowercase
    normalized = title.lower()

    # Remove everything after any "-", "(", "[",
    normalized = normalized.split(' - ')[0].split(' (')[0].split(' [')[0]
    
    # Remove content in parentheses and brackets (live, explicit, feat, etc.)
    normalized = re.sub(r'\s*[\(\[].*?[\)\]]', '', normalized)
    
    # Remove "feat.", "ft.", "with", "con", "part." and everything after
    normalized = re.sub(r'\s+(feat\.|ft\.|featuring|with|con|part\.).*$', '', normalized)
    
    # Remove special characters except spaces
    normalized = re.sub(r'[^\w\s]', '', normalized)
    
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # remove any character not a letter, number or space
    normalized = re.sub(r'[^a-zA-Z0-9\s]', '', normalized)
    
    return normalized

def scrape_lastfm_tracks(artist_name, max_pages=10):
    """Scrape all tracks from Last.fm for the given artist."""
    all_tracks = set()
    encoded_artist = urllib.parse.quote(artist_name)
    base_url = f"https://www.last.fm/music/{encoded_artist}/+tracks"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    page = 1
    while page <= max_pages:
        url = f"{base_url}?date_preset=ALL&page={page}"
        print(f"Scraping page {page}...")
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find track titles
            track_elements = soup.find_all('td', class_='chartlist-name')
            
            if not track_elements:
                print(f"No more tracks found on page {page}.")
                break
            
            for track in track_elements:
                link = track.find('a')
                if link:
                    track_title = link.get_text(strip=True)
                    normalized = normalize_track(track_title)
                    
                    if normalized:
                        all_tracks.add(normalized)
            
            print(f"Found {len(track_elements)} tracks on page {page}")
            page += 1
            time.sleep(1)
            
        except requests.RequestException as e:
            print(f"Error fetching page {page}: {e}")
            break
    
    return all_tracks

def find_missing_tracks(folder_path, artist_name, max_pages=10):
    """Find tracks by artist that are not in the FLAC folder."""
    print(f"\n=== Finding missing tracks for '{artist_name}' ===\n")
    
    # Get tracks from FLAC files
    print(f"Scanning FLAC files by '{artist_name}' in: {folder_path}")
    flac_tracks = get_artist_tracks_from_flacs(folder_path, artist_name)
    print(f"Found {len(flac_tracks)} tracks by this artist in FLACs\n")
    
    # Scrape Last.fm tracks
    print(f"Scraping Last.fm for '{artist_name}'...")
    lastfm_tracks = scrape_lastfm_tracks(artist_name, max_pages)
    print(f"\nUnique tracks found on Last.fm: {len(lastfm_tracks)}\n")
    
    # Find missing tracks by comparing sets
    missing_tracks = lastfm_tracks - flac_tracks
    missing_tracks = list(missing_tracks)
    
    # Display results
    print("=" * 60)
    print(f"MISSING TRACKS ({len(missing_tracks)}):")
    print("=" * 60)
    
    if missing_tracks:
        for i, track in enumerate(missing_tracks, 1):
            print(f"{i}. {track}")
    else:
        print("No missing tracks! You have all songs from Last.fm.")
    
    print("\n" + "=" * 60)
    print(f"Summary:")
    print(f"  - Tracks by artist in FLACs: {len(flac_tracks)}")
    print(f"  - Unique tracks on Last.fm: {len(lastfm_tracks)}")
    print(f"  - Missing tracks: {len(missing_tracks)}")
    print("=" * 60)
    
    return missing_tracks

if __name__ == "__main__":
    # Example usage
    folder_path = "D:/Music/My Playlist"
    # folder_path = input("Enter the path to your FLAC folder: ").strip()
    artist_name = input("Enter the artist name: ").strip()
    max_pages = None
    # max_pages = input("Max pages to scrape (default 10): ").strip()
    
    max_pages = int(max_pages) if max_pages else 10
    
    missing = find_missing_tracks(folder_path, artist_name, max_pages)