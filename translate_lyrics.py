import mutagen
from mutagen.flac import FLAC
import os
import readline
import re
from deep_translator import GoogleTranslator  # Add Google Translate import
import time  # For rate limiting
from langdetect import detect, LangDetectException
from langdetect.detector_factory import DetectorFactory

# Set seed once at module level for deterministic results
DetectorFactory.seed = 0

def get_unsynced_lyrics(file_path: str) -> str:
    try:
        audio = FLAC(file_path)
        return audio.get("lyrics", [""])[0]
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

def translate_line(text, translator):
    """Translate text using Google Translate with error handling"""
    if not text.strip():
        return None
        
    try:
        # Translate to English
        translated = translator.translate(text)
        # Only return translation if it's different from original
        if normalize_text(translated) != normalize_text(text):
            print(f"Translated '{text}' to '{translated}'")
            return translated
        return None
    except Exception as e:
        print(f"Translation error for '{text}': {e}")
        return None

def needs_translation(lyrics: str) -> bool:
    """Check if lyrics contain non-English text that needs translation"""
    if not lyrics:
        return False
    
    try:
        text_to_check = re.sub(r'[^\w\s]', '', lyrics).strip()
        
        if not text_to_check or len(text_to_check) < 3:
            return False
        
        detected_lang = detect(text_to_check)
        return detected_lang != 'en'
    
    except LangDetectException:
        # Fallback for very short or ambiguous text
        non_ascii = len(re.findall(r'[^\x00-\x7F]', lyrics))
        ascii_letters = len(re.findall(r'[a-zA-Z]', lyrics))
        return non_ascii > ascii_letters * 0.1

def translate_lyrics(directory):
    translator = GoogleTranslator(source='auto', target='en')

    files = os.listdir(directory)

    file_paths = []
    for file in files:
        if file.endswith(".flac"):
            file_paths.append(file)

    for i, file in enumerate(file_paths, 1):
        print(f"{i}. {file}")

        file_path = os.path.join(directory, file)
        lyrics = get_unsynced_lyrics(file_path)
        lyrics = sort_by_time(lyrics)

        if not needs_translation(lyrics):
            print("No translation needed.")
            continue

        print("Lyrics:\n", lyrics)

        if input("Translate? y/n: ").lower() != "y":
            continue

        # Initialize translator with rate limiting
        section_markers = {"chorus", "bridge", "verse", "instrumental", "outro", 
                        "interlude", "pre-chorus", "intro", "hook"}

        fixed = []
        for line in lyrics.split("\n"):
            line = line.strip()
            if not line:
                fixed.append("")  # Preserve empty lines
                continue
                
            # Extract actual lyric text (last part after all timestamps)
            parts = line.split(']')
            text_content = parts[-1].strip()
            
            # Skip pure timestamp lines
            if not text_content:
                fixed.append(line)
                continue
                
            # Skip section markers
            if text_content.lower() in section_markers:
                fixed.append(line)
                continue
                
            # Reconstruct full timestamps prefix
            timestamps_part = ']'.join(parts[:-1]) + ']' if len(parts) > 1 else ''
            
            # Add original line
            fixed.append(line)
            
            # Translate and add if different
            translated = translate_line(text_content, translator)
            if translated:
                if timestamps_part:
                    fixed.append(f"{timestamps_part} ({translated})")
                else:
                    fixed.append(f"({translated})")
                # Add delay to avoid rate limiting
                time.sleep(0.5)

        fixed_lyrics = "\n".join(fixed)
        print("Fixed lyrics:\n", fixed_lyrics)

        if input("Edit new lyrics? (y/n): ").lower() == "y":
            print("Lines:", len(fixed))
            while True:
                line = input("Line to be edited or 'q' to quit: ")
                
                if line == "q":
                    break
                
                line_index = int(line) - 1
                if line_index < 0 or line_index >= len(fixed):
                    print("Invalid line number.")
                    continue

                print(f"Current line: {fixed[line_index]}")
                
                new_line = input("New line: ")
                fixed[line_index] = new_line

        if input("Apply new lyrics? (y/n): ").lower() == "y":
            try:
                audio = FLAC(file_path)
                audio["lyrics"] = fixed_lyrics
                audio.save()
                print("New lyrics applied successfully.")
            except mutagen.MutagenError as e:
                print(f"Error applying lyrics: {e}")

if __name__ == "__main__":
    translate_lyrics("/home/adam/driveBig/Music/New unformated songs")