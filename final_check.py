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

def confirm_and_move(directory, new_directory):
    flacs = get_flacs(directory)
    required_tags = ["artist", "title", "album", "date", "UNSYNCED LYRICS", "albumartist", "replaygain_album_gain", 'replaygain_album_peak', 'replaygain_track_gain', "replaygain_track_peak"]

    for flac in flacs:
        audio_file = FLAC(flac)
        print(f"\nChecking: {flac}")

        # Check if all required tags are present
        for tag in required_tags:
            if tag not in audio_file or not audio_file[tag]:
                print(f"Missing '{tag}' for {os.path.basename(flac)}. Skipping.")
                continue

        # Check if the date is in the correct format
        if len(audio_file["date"][0]) != 4:
            print(f"Invalid date format for {os.path.basename(flac)}. Skipping.")
            continue

        # Check if the artist is in the correct format
        artist = audio_file["artist"][0]

        artist = re.sub(r"\s*(,|&|feat\.?|ft\.?|featuring)\s*", "; ", artist, flags=re.IGNORECASE)

        artist = re.sub(r"(; )+", "; ", artist).strip("; ").strip()

        if artist != audio_file["artist"][0]:
            print(f"Invalid artist format for {os.path.basename(flac)}. Skipping.")
            continue

        # Check if the filename is in the correct format
        filename = os.path.basename(flac)
        if filename != f"{audio_file['title'][0]} - {audio_file['artist'][0]}{' - ' + audio_file['album'][0] if audio_file['album'] != audio_file['title'] else ''}.flac":
            print(f"Invalid filename format for {os.path.basename(flac)}. Skipping.")
            continue

        # Check if the file already exists in the new directory
        new_path = os.path.join(new_directory, filename)
        if os.path.exists(new_path):
            print(f"File {filename} already exists in the new directory. Skipping.")
            continue

        print(f"File {filename} is ready to be moved to the new directory.")
        
        # Print tags and ask for confirmation
        for tag in required_tags:
            print(f"{tag}: {audio_file[tag][0]}")

        print(f"Filename: {filename}")

        confirm = input("Do you want to move this file to the new directory? (y/n): ")
        if confirm.lower() != "y":
            print("Skipping file.")
            continue

        # Move the file to the root directory
        new_path = os.path.join(new_directory, filename)
        try:
            os.rename(flac, new_path)
        except:
            print(f"Failed to move {flac} to {new_path}, likely because it already exists. Skipping.")

if __name__ == "__main__":
    confirm_and_move("D:/Music/New unformated songs", "D:/Music/My Playlist")