import os
import readline
import re
from mutagen.flac import FLAC

def get_flacs(directory):
    """Get all FLAC files in a directory and their tags."""
    flac_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".flac"):
                flac_files.append(os.path.join(root, file))
    return flac_files

def sanitize_filename(filename):
    """Remove or replace characters that are invalid in Windows filenames."""
    replacements = {
        ':': ' -', '/': '-', '\\': '-', '|': '-', '?': '',
        '*': '', '"': "'", '<': '', '>': ''
    }
    for old, new in replacements.items():
        filename = filename.replace(old, new)
    return filename.rstrip('. ')

def confirm(prompt):
    """Ask user to confirm an action."""
    choice = input(f"{prompt} (y/n): ").strip().lower()
    return choice == 'y'

def fix_tags(directory):
    flacs = get_flacs(directory)
    required_tags = ["artist", "title", "album", "date", "albumartist"]
    
    # Dictionary to store user preferences for artist formatting
    artist_preferences = {}
    # Dictionary to store user preferences for filename changes
    rename_preferences = {}
    
    total = len(flacs)
    
    for idx, flac in enumerate(flacs, 1):
        print(f"\n[{idx}/{total}] 🎧 Checking: {flac}")
        audio_file = FLAC(flac)
        updated = False

        # Fill missing tags
        for tag in required_tags:
            if tag not in audio_file or not audio_file[tag]:
                if tag == "albumartist" and "artist" in audio_file and audio_file["artist"][0]:
                    print(f"Missing '{tag}', can auto-fill with artist: {audio_file['artist'][0]}")
                    if confirm("Apply this change?"):
                        audio_file["albumartist"] = audio_file["artist"]
                        updated = True
                    continue

                print(f"Missing '{tag}' for {os.path.basename(flac)}.")
                value = input(f"Enter value for {tag}: ").strip()
                if value and confirm(f"Set {tag} = '{value}'?"):
                    audio_file[tag] = [value]
                    updated = True

        # Normalize date tag to YYYY
        if "date" in audio_file and audio_file["date"]:
            date_val = audio_file["date"][0]
            if len(date_val) != 4:
                new_date = date_val[:4]
                if confirm(f"Change date '{date_val}' → '{new_date}'?"):
                    audio_file["date"] = [new_date]
                    updated = True

        # Clean up artist formatting
        artist = audio_file["artist"][0]
        formatted_artist = re.sub(
            r"\s*(?:,|&|\b(?:feat\.?|ft\.?|featuring)\b)\s*",
            "; ",
            artist,
            flags=re.IGNORECASE
        )
        formatted_artist = re.sub(r"(; )+", "; ", formatted_artist).strip("; ").strip()
        
        if formatted_artist != artist:
            # Check if we've already asked about this specific formatting change
            change_key = (artist, formatted_artist)
            if change_key not in artist_preferences:
                artist_preferences[change_key] = confirm(f"Change artist '{artist}' → '{formatted_artist}'?")
            
            if artist_preferences[change_key]:
                audio_file["artist"] = [formatted_artist]
                updated = True

        # Remove "(album version)"
        title = audio_file["title"][0]
        if "(album version)" in title.lower():
            new_title = re.sub(r"\(album version\)", "", title, flags=re.IGNORECASE).strip()
            if confirm(f"Change title '{title}' → '{new_title}'?"):
                audio_file["title"] = [new_title]
                updated = True

        # Handle remaster pattern
        remaster_match = re.search(r"(?:\(| - )(\d{4}) Remaster\)?", title)
        if remaster_match:
            year = remaster_match.group(1)
            clean_title = re.sub(r"(?:\(| - )\d{4} Remaster\)?", "", title).strip()
            new_album = audio_file["album"][0]
            if f"{year} Remaster" not in new_album:
                new_album = f"{new_album} ({year} Remaster)"
            print(f"Detected remaster year {year}.")
            if confirm(f"Change title '{title}' → '{clean_title}' and album → '{new_album}'?"):
                audio_file["title"] = [clean_title]
                audio_file["album"] = [new_album]
                updated = True

        if " - Single" in audio_file["album"][0]:
            new_album = audio_file["album"][0].replace(" - Single", "")
            if confirm(f"Change album '{audio_file['album'][0]}' → '{new_album}'?"):
                audio_file["album"] = [new_album]
                updated = True

        if updated:
            audio_file.save()
            print(f"✅ Tags updated for: {flac}")
        else:
            print(f"✔ No tag changes needed for: {flac}")

        # Construct expected filename
        expected_name = f"{audio_file['title'][0]} - {audio_file['artist'][0]}"
        if audio_file['album'][0] != audio_file['title'][0]:
            expected_name += f" - {audio_file['album'][0]}"
        expected_name += ".flac"
        expected_name = sanitize_filename(expected_name)

        current_name = os.path.basename(flac)

        if current_name != expected_name:
            print(f"Filename differs:\n  Current: {current_name}\n  Expected: {expected_name}")
            
            # Create a key based on the type of change (e.g., "AC,DC" -> "AC-DC")
            # Extract the pattern of the change to reuse the decision
            rename_pattern = None
            if "AC,DC" in current_name and "AC-DC" in expected_name:
                rename_pattern = "AC,DC->AC-DC"
            
            # Check if we've already made a decision on this type of rename
            should_rename = None
            if rename_pattern and rename_pattern in rename_preferences:
                should_rename = rename_preferences[rename_pattern]
            else:
                should_rename = confirm("Rename file?")
                if rename_pattern:
                    rename_preferences[rename_pattern] = should_rename
            
            if should_rename:
                new_path = os.path.join(os.path.dirname(flac), expected_name)
                try:
                    os.rename(flac, new_path)
                    print(f"✅ Renamed to: {expected_name}")
                except FileExistsError:
                    alt_name = expected_name.replace('.flac', ' (1).flac')
                    os.rename(flac, os.path.join(os.path.dirname(flac), alt_name))
                    print(f"⚠️ File exists. Saved as: {alt_name}")
        else:
            print(f"✔ Filename already correct: {current_name}")

if __name__ == "__main__":
    fix_tags("/home/adam/driveBig/Music/My Playlist")