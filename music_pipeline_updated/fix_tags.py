import os
import readline
import re
from mutagen.flac import FLAC

from change_display import (
    auto_applied_note, format_change, format_inline, is_case_only,
)

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
        ':': '-', '/': '-', '\\': '-', '|': '-', '?': '',
        '*': '', '"': "'", '<': '', '>': ''
    }
    for old, new in replacements.items():
        filename = filename.replace(old, new)
    return filename.rstrip('. ')

def confirm(prompt):
    """Ask user to confirm an action."""
    choice = input(f"{prompt} (y/n): ").strip().lower()
    return choice == 'y'


def confirm_change(what, old, new):
    """
    Show a change with the differing part highlighted, then ask to apply it.

    If the only difference is capitalisation, this returns True without
    asking anything - it just prints what it did. Everything else is a
    normal y/n.
    """
    print(f"{what}:")
    print(format_change(old, new, old_label="Current", new_label="New"))
    if is_case_only(old, new):
        print(auto_applied_note("change"))
        return True
    return confirm("Apply this change?")


def rename_preserving_case(src, dst_name):
    """
    Rename `src` to `dst_name` in the same folder.

    A case-only rename has to go via a temporary name, because on a
    case-insensitive filesystem (Windows, and macOS by default) the source
    and destination are literally the same file, so a direct rename is
    either a no-op or an error. Returns the name it ended up using.
    """
    folder = os.path.dirname(src)
    dst = os.path.join(folder, dst_name)
    src_name = os.path.basename(src)

    if is_case_only(src_name, dst_name):
        tmp = os.path.join(folder, f".{dst_name}.case-rename")
        os.rename(src, tmp)
        os.rename(tmp, dst)
        return dst_name

    if os.path.exists(dst):
        raise FileExistsError(dst)
    os.rename(src, dst)
    return dst_name

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
                if confirm_change("Date tag", date_val, new_date):
                    audio_file["date"] = [new_date]
                    updated = True

       # Clean up artist formatting
        artist = audio_file["artist"][0]
        # Matches commas, ampersands, or feature tags (with surrounding whitespace)
        formatted_artist = re.sub(
            r"\s*(?:,|&|\b(?:feat\.?|ft\.?|featuring)\b)\s*",
            "; ",
            artist,
            flags=re.IGNORECASE
        )
        # Collapse multi-semicolons and strip dangling punctuation
        formatted_artist = re.sub(r"\s*;\s*", "; ", formatted_artist)
        formatted_artist = re.sub(r"(;\s*)+", "; ", formatted_artist).strip("; ").strip() 
        
        if formatted_artist != artist:
            # Check if we've already asked about this specific formatting change
            change_key = (artist, formatted_artist)
            if change_key not in artist_preferences:
                artist_preferences[change_key] = confirm_change(
                    "Artist tag", artist, formatted_artist)
            
            if artist_preferences[change_key]:
                audio_file["artist"] = [formatted_artist]
                updated = True

        # Remove "(album version)"
        title = audio_file["title"][0]
        if "(album version)" in title.lower():
            new_title = re.sub(r"\(album version\)", "", title, flags=re.IGNORECASE).strip()
            if confirm_change("Title tag", title, new_title):
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
            old_album = audio_file["album"][0]
            print(f"Detected remaster year {year}.")
            print("Title tag:")
            print(format_change(title, clean_title, old_label="Current", new_label="New"))
            print("Album tag:")
            print(format_change(old_album, new_album, old_label="Current", new_label="New"))
            # Only skip the prompt if *both* halves are case-only changes.
            case_only_pair = ((title == clean_title or is_case_only(title, clean_title))
                              and (old_album == new_album or is_case_only(old_album, new_album)))
            if case_only_pair:
                print(auto_applied_note("change"))
                apply_it = True
            else:
                apply_it = confirm("Apply this change?")
            if apply_it:
                audio_file["title"] = [clean_title]
                audio_file["album"] = [new_album]
                updated = True

        if " - Single" in audio_file["album"][0]:
            new_album = audio_file["album"][0].replace(" - Single", "")
            if confirm_change("Album tag", audio_file["album"][0], new_album):
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
            print("Filename differs:")
            print(format_change(current_name, expected_name,
                                old_label="Current", new_label="Expected"))

            if is_case_only(current_name, expected_name):
                # Capitalisation only - just do it, don't ask.
                print(auto_applied_note("rename"))
                should_rename = True
            else:
                # Create a key based on the type of change (e.g., "AC,DC" -> "AC-DC")
                # Extract the pattern of the change to reuse the decision
                rename_pattern = None
                if "AC,DC" in current_name and "AC-DC" in expected_name:
                    rename_pattern = "AC,DC->AC-DC"

                # Check if we've already made a decision on this type of rename
                if rename_pattern and rename_pattern in rename_preferences:
                    should_rename = rename_preferences[rename_pattern]
                else:
                    should_rename = confirm("Rename file?")
                    if rename_pattern:
                        rename_preferences[rename_pattern] = should_rename

            if should_rename:
                try:
                    rename_preserving_case(flac, expected_name)
                    print(f"✅ Renamed to: {expected_name}")
                except FileExistsError:
                    alt_name = expected_name.replace('.flac', ' (1).flac')
                    os.rename(flac, os.path.join(os.path.dirname(flac), alt_name))
                    print(f"⚠️ File exists. Saved as: {alt_name}")
                except OSError as e:
                    print(f"⚠️ Could not rename {current_name}: {e}")
        else:
            print(f"✔ Filename already correct: {current_name}")

if __name__ == "__main__":
    fix_tags("/home/adam/driveBig/Music/New unformated songs")