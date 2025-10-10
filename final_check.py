import os
from mutagen.flac import FLAC
import re
import unicodedata

def get_flacs(directory):
    """Get all FLAC files in a directory and their tags."""
    flac_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".flac"):
                full_path = os.path.join(root, file)
                flac_files.append(full_path)
    return flac_files

def normalize(s):
    return unicodedata.normalize("NFKC", s).strip().lower()

def sanitize_filename(filename):
    """Remove or replace characters that are invalid in Windows filenames."""
    replacements = {
        ':': ' -', '/': '-', '\\': '-', '|': '-', '?': '',
        '*': '', '"': "'", '<': '', '>': ''
    }
    for old, new in replacements.items():
        filename = filename.replace(old, new)
    return filename.rstrip('. ')

def ask_skip(message):
    """Ask user if they want to skip this check."""
    response = input(f"{message}\nSkip this check for this file? (y/n): ").strip().lower()
    return response == "y"

def confirm_and_move(directory, new_directory):
    flacs = get_flacs(directory)
    required_tags = [
        "artist", "title", "album", "date", "UNSYNCED LYRICS",
        "albumartist", "replaygain_album_gain", "replaygain_album_peak",
        "replaygain_track_gain", "replaygain_track_peak"
    ]

    for flac in flacs:
        audio_file = FLAC(flac)
        print(f"\nChecking: {flac}")

        # --- Check for missing tags ---
        missing_tag = False
        for tag in required_tags:
            if tag not in audio_file or not audio_file[tag]:
                print(f"Missing '{tag}' for {os.path.basename(flac)}.")
                if ask_skip("This tag is missing."):
                    continue
                missing_tag = True
                break
        if missing_tag:
            continue

        # --- Date format check ---
        if len(audio_file["date"][0]) != 4:
            msg = f"Invalid date format for {os.path.basename(flac)} ({audio_file['date'][0]} not in YYYY format)."
            if not ask_skip(msg):
                print("Skipping file.")
                continue

        # --- Artist format check ---
        artist = audio_file["artist"][0]
        formatted_artist = re.sub(r"\s*(?:,|&|\b(?:feat\.?|ft\.?|featuring)\b)\s*", "; ", artist, flags=re.IGNORECASE)
        formatted_artist = re.sub(r"(; )+", "; ", formatted_artist).strip("; ").strip()
        if normalize(formatted_artist) != normalize(artist):
            msg = f"Invalid artist format for {os.path.basename(flac)}: {artist}"
            if not ask_skip(msg):
                print("Skipping file.")
                continue

        # --- Filename format check ---
        filename = os.path.basename(flac)
        expected_filename = f"{audio_file['title'][0]} - {audio_file['artist'][0]}{' - ' + audio_file['album'][0] if audio_file['album'] != audio_file['title'] else ''}.flac"
        expected_filename = sanitize_filename(expected_filename)

        if normalize(filename) != normalize(expected_filename):
            print(f"Invalid filename format for {os.path.basename(flac)}.")
            for i, (a, b) in enumerate(zip(filename, expected_filename)):
                if a != b:
                    print(f"Difference at position {i}: '{a}' vs '{b}'")
            if not ask_skip("Filename format differs."):
                print("Skipping file.")
                continue

        # --- Album image check ---
        if not audio_file.pictures:
            msg = f"No album image for {os.path.basename(flac)}."
            if not ask_skip(msg):
                print("Skipping file.")
                continue

        # --- Duplicate in destination ---
        new_path = os.path.join(new_directory, filename)
        if os.path.exists(new_path):
            msg = f"File {filename} already exists in the new directory."
            if not ask_skip(msg):
                print("Skipping file.")
                continue

        # --- Final confirmation ---
        print(f"\n✅ File {filename} is ready to be moved to the new directory.")
        for tag in required_tags:
            print(f"{tag}: {audio_file[tag][0]}")
        print(f"Filename: {filename}")

        confirm = input("Move this file? (y/n): ").strip().lower()
        if confirm != "y":
            print("Skipping file.")
            continue

        # --- Move file ---
        try:
            os.rename(flac, new_path)
            print(f"Moved {filename} successfully.")
        except Exception as e:
            print(f"⚠️ Failed to move {flac} → {new_path}: {e}")

if __name__ == "__main__":
    confirm_and_move("D:/Music/New unformated songs", "D:/Music/My Playlist")