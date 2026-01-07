# get list of files from directory
import os
import readline

unfiltered_files = os.listdir("D:/Music/My Playlist")
files = []
spotify = []
file_artists = []
spotify_artists = []

unfiltered_files.sort()

for file in unfiltered_files:
    if file.endswith(".flac"):
        files.append(file.split(" - ")[0].split("(")[0].lower().strip())
        split = file.split(" - ")
        split.pop(0)
        file_artists.append(" - ".join(split))

# get list of files from spotify
import requests
import re
from typing import List, Optional

class PlaylistExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def extract_spotify_playlist_id(self, url: str) -> Optional[str]:
        """Extract playlist ID from Spotify URL"""
        patterns = [
            r'spotify\.com/playlist/([a-zA-Z0-9]+)',
            r'open\.spotify\.com/playlist/([a-zA-Z0-9]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_spotify_access_token(self) -> Optional[str]:
        """
        Get access token from Spotify's web player
        Note: This is a simplified approach. For production use,
        implement proper OAuth2 flow with client credentials.
        """
        try:
            # This would need to be implemented with proper Spotify API credentials
            # For demo purposes, showing the structure
            print("Note: You need to set up Spotify API credentials")
            print("Visit: https://developer.spotify.com/dashboard/")
            return None
        except Exception as e:
            print(f"Error getting access token: {e}")
            return None
    
    def get_spotify_playlist_tracks(self, playlist_id: str, access_token: str) -> List[str]:
        """Get track titles from Spotify playlist using API"""
        tracks = []
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            while url:
                response = self.session.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                for item in data.get('items', []):
                    track = item.get('track')
                    if track and track.get('name'):
                        artist_names = [artist['name'] for artist in track.get('artists', [])]
                        artist_str = ', '.join(artist_names)
                        title = f"{track['name']} - {artist_str}" if artist_str else track['name']
                        tracks.append(title)
                
                url = data.get('next')  # Pagination
                
        except requests.exceptions.RequestException as e:
            print(f"Error fetching playlist: {e}")
        
        return tracks

def main():
    global spotify, files
    """
    Main function demonstrating usage
    """
    extractor = PlaylistExtractor()
    
    print("Playlist Song Title Extractor")
    print("-" * 40)
    
    # Example usage
    # playlist_url = input("Enter playlist URL: ").strip()

    # Process actual URL
    playlist_id = "2cZy3ovKrkKHCWe9UllDMm" # extractor.extract_spotify_playlist_id(playlist_url)

    print(f"Extracted Spotify Playlist ID: {playlist_id}")
    
    access_token = "BQDngQsogcdxG184eq_CdXlHcz4yaHgTJ2d4mo9k9jLYHSDCdGL8NMn-lUiSFDgC3Z4r9eZzqqE58TBnC2PJFntNDroaRmlAfTv65UgH4DJIWRiMU9liQ1fOCJf-cUIxUFyscSAgwEPgnBPJky-UfYPXB7I-rwPmo6eA0DOmQuypmZlA01CyIo4ADwe8InxvD7Ty7DCHuXehW1yHyWYdSx0BQ78"

    tracks = extractor.get_spotify_playlist_tracks(playlist_id, access_token)

    tracks.sort()

    for track in tracks:
        spotify.append(track.split(" - ")[0].split("(")[0].lower().strip())
        split = track.split(" - ")
        split.pop(0)
        spotify_artists.append(" - ".join(split))


    print("-" * 80)
    print(f"{"Not in Spotify".center(80)} | {"Not in Files".center(80)}")
    print("-" * 80)

    # find all songs not in both
    not_in_spotify = [
        f"{song} - {file_artists[files.index(song)]}" for song in files if song not in spotify
    ]
    not_in_files = [
        f"{song} - {spotify_artists[spotify.index(song)]}" for song in spotify if song not in files
    ]

    # Calculate max length to zip safely
    max_len = max(len(not_in_spotify), len(not_in_files))

    # sort both by artists
    not_in_spotify.sort(key=lambda x: x.split(" - ")[1] if " - " in x else "")
    not_in_files.sort(key=lambda x: x.split(" - ")[1] if " - " in x else "")

    # Pad shorter list with empty strings
    not_in_spotify += [""] * (max_len - len(not_in_spotify))
    not_in_files += [""] * (max_len - len(not_in_files))

    # Remove file extensions
    not_in_spotify = [not_in_spotify[i].split(".")[0] for i in range(max_len)]

    # Print side-by-side
    for s1, s2 in zip(not_in_spotify, not_in_files):
        title1, artist1, album1, title2, artist2, album2 = "", "", "", "", "", ""
        parts = s1.split(" - ")
        if len(parts) >= 3:
            title1, artist1, album1 = parts[0], parts[1], parts[2]
        parts = s2.split(" - ")
        if len(parts) >= 3:
            title2, artist2, album2 = parts[0], parts[1], parts[2]
        # cut strings to 30 chars
        title1 = title1[:30]
        artist1 = artist1[:30]
        album1 = album1[:30]
        title2 = title2[:30]
        artist2 = artist2[:30]
        album2 = album2[:30]
        print(f"{title1:<30} | {artist1:<30} | {album1:<30} | {title2:<30} | {artist2:<30} | {album2:<30}")

    print("-" * 80)

    print(f"Song not in Spotify: {len(not_in_spotify)}")
    print(f"Song not in Files: {len(not_in_files)}")


if __name__ == "__main__":
    main()
    print("\n" + "="*50)