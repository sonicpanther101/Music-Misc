import os
from mutagen.flac import FLAC
import re

def get_flacs(directory):
    """Get all FLAC files in a directory and their tags."""
    flac_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".flac"):
                full_path = os.path.join(root, file)
                flac_files.append(full_path)
    
    return flac_files

def fix_tags(directory):
    flacs = get_flacs(directory)
    required_tags = ["artist", "title", "album", "date", "UNSYNCED LYRICS", "albumartist"]

    for flac in flacs:
        audio_file = FLAC(flac)
        print(f"\nChecking: {flac}")

        updated = False
        for tag in required_tags:
            if tag not in audio_file or not audio_file[tag]:
                value = input(f"Missing '{tag}' for {os.path.basename(flac)}. Enter value: ").strip()
                if value:
                    audio_file[tag] = value
                    updated = True

        if len(audio_file["date"][0]) != 4:
            audio_file["date"] = audio_file["date"][0][:4]
            updated = True

        artist = audio_file["artist"][0]

        artist = re.sub(r"\s*(,|&|feat\.?|ft\.?|featuring)\s*", "; ", artist, flags=re.IGNORECASE)

        artist = re.sub(r"(; )+", "; ", artist).strip("; ").strip()

        if artist != audio_file["artist"][0]:
            audio_file["artist"][0] = artist
            updated = True
        
        if "(album version)" in audio_file["title"][0]:
            audio_file["title"][0] = audio_file["title"][0].replace("(album version)", "").strip()
            updated = True
        
        # Matches "(YYYY Remaster)" or " - YYYY Remaster"
        remaster_match = re.search(r"(?:\(| - )(\d{4}) Remaster\)?", audio_file["title"][0])
        if remaster_match:
            year = remaster_match.group(1)
            # Remove the remaster part from the title
            audio_file["title"][0] = re.sub(r"(?:\(| - )\d{4} Remaster\)?", "", audio_file["title"][0]).strip()
            # Append to album if not already present
            if f"{year} Remaster" not in audio_file["album"][0]:
                audio_file["album"][0] += f" ({year} Remaster)"
            updated = True
        
        if updated:
            audio_file.save()
            print(f"✅ Updated tags for: {flac}")
        else:
            print(f"✔ All required tags present for: {flac}")

        # check name isnt already correct
        if f"{audio_file['title'][0]} - {audio_file['artist'][0]}{' - ' + audio_file['album'][0] if audio_file['album'] != audio_file['title'] else ''}.flac" == os.path.basename(flac):
            print(f"✔ Name already correct for: {flac}")
            continue
        
        # rename the file to %title% - %artist%$if($equal(%album%,%title%),, - %album%)
        new_name = f"{audio_file['title'][0]} - {audio_file['artist'][0]}{' - ' + audio_file['album'][0] if audio_file['album'] != audio_file['title'] else ''}.flac"
        new_path = os.path.join(os.path.dirname(flac), new_name)
        os.rename(flac, new_path)
        print(f"✅ Renamed file to: {new_path}")


if __name__ == "__main__":
    fix_tags("D:/Music/New unformated songs")
