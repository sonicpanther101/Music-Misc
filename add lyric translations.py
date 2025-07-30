import mutagen
from mutagen.flac import FLAC
import os
import re

files = os.listdir("C:/Users/adam/music/my playlist")

def get_unsynced_lyrics(file_path: str) -> str:
    try:
        audio = FLAC(file_path)
        return audio.get("UNSYNCED LYRICS", [""])[0]
    except mutagen.MutagenError as e:
        print(f"Error retrieving lyrics: {e}")
        return ""

def sort_by_time(lyrics: str) -> str:
    lines = lyrics.split("\n")
    
    def parse_timestamp(line):
        if not line.strip() or not line.startswith('['):
            return float('inf')
        try:
            timestamp_part = line.split(']')[0][1:]
            minutes, seconds = timestamp_part.split(':')
            total_seconds = int(minutes) * 60 + float(seconds)
            return total_seconds
        except (ValueError, IndexError):
            return float('inf')
    
    sorted_lines = sorted(lines, key=parse_timestamp)
    return "\n".join(sorted_lines)

def normalize_text(text):
    """Normalize text for matching: lowercase and remove punctuation"""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    return text.strip()

def main():
    file = input("Enter the name of the file: ")
    if file not in files:
        print("File not found!")
        return
    
    print("File found!")
    file_path = os.path.join("C:/Users/adam/music/my playlist", file)
    lyrics = get_unsynced_lyrics(file_path)
    lyrics = sort_by_time(lyrics)
    print("Lyrics:\n", lyrics)

    print("Enter the lyrics with translation (end with 'end'):")
    english_lines = []
    while True:
        line = input()
        if line.strip() == "end":
            break
        section_markers = {"chorus", "bridge", "verse", "instrumental", "outro", 
                          "interlude", "pre-chorus", "intro", "hook"}
        if line.strip().lower() in section_markers:
            continue
        english_lines.append(line)
    
    # Build translation map with normalized keys
    translation_map = {}
    for i in range(0, len(english_lines), 2):
        if i+1 < len(english_lines):
            original_text = english_lines[i].strip()
            translated_text = english_lines[i+1].strip()
            # Use normalized key for matching
            norm_key = normalize_text(original_text)
            translation_map[norm_key] = translated_text

    fixed = []
    for line in lyrics.split("\n"):
        line = line.strip()
        if not line:
            continue
            
        # Extract actual lyric text (last part after all timestamps)
        parts = line.split(']')
        text_content = parts[-1].strip()
        
        # Skip pure timestamp lines
        if not text_content:
            fixed.append(line)
            continue
            
        # Lookup translation using normalized text
        norm_text = normalize_text(text_content)
        translated = translation_map.get(norm_text, "NO_TRANSLATION")
        
        # Reconstruct full timestamps prefix
        timestamps_part = ']'.join(parts[:-1]) + ']' if len(parts) > 1 else ''
        
        # Format: original line + translation line
        fixed.append(line)
        if timestamps_part:
            fixed.append(f"{timestamps_part} ({translated})")
        else:
            fixed.append(f"({translated})")

    fixed_lyrics = "\n".join(fixed)
    print("Fixed lyrics:\n", fixed_lyrics)

    if input("Apply new lyrics: ") == "y":
        try:
            audio = FLAC(file_path)
            audio["UNSYNCED LYRICS"] = fixed_lyrics
            audio["LYRICS"] = fixed_lyrics
            audio.save()
            print("New lyrics applied successfully.")
        except mutagen.MutagenError as e:
            print(f"Error applying lyrics: {e}")

if __name__ == "__main__":
    main()