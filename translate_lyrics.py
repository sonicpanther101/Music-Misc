import mutagen
from mutagen.flac import FLAC
import os
import readline
import re
from deep_translator import GoogleTranslator  # Add Google Translate import
import time  # For rate limiting
from langdetect import detect, LangDetectException
from langdetect.detector_factory import DetectorFactory
import unicodedata

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

def normalize_punctuation(text: str) -> str:
    normalized = text
    normalized = re.sub(r'[\uff01-\uff60]', lambda m: chr(ord(m.group()) - 0xfee0), normalized)  # fullwidth
    normalized = re.sub(r'[\u2018\u2019\u201a\u201b\u2032\u2033\u02bc\u0060\u00b4]', "'", normalized)  # single quotes/primes
    normalized = re.sub(r'[\u201c\u201d\u201e\u201f]', '"', normalized)  # double quotes
    normalized = re.sub(r'[\u2013\u2014]', '-', normalized)              # dashes
    normalized = normalized.replace('\xa0', ' ')                          # non-breaking space
    normalized = normalized.replace('\u0435', 'e')                        # Cyrillic е → Latin e
    normalized = normalized.replace('\u0430', 'a')                        # Cyrillic а → Latin a (preemptive)
    normalized = normalized.replace('\u043e', 'o')                        # Cyrillic о → Latin o (preemptive)
    normalized = normalized.replace('\u0440', 'r')                        # Cyrillic р → Latin r (preemptive)
    normalized = normalized.replace('\x92', "'")                          # Windows-1252 right single quote
    normalized = normalized.replace('\x91', "'")                          # Windows-1252 left single quote (preemptive)
    normalized = normalized.replace('\x93', '"')                          # Windows-1252 left double quote (preemptive)
    normalized = normalized.replace('\x94', '"')                          # Windows-1252 right double quote (preemptive)
    normalized = normalized.replace('\ufeff', '')                          # BOM / zero-width no-break space
    # Unicode whitespace variants → regular space
    normalized = re.sub(r'[\u00a0\u2000-\u200b\u202f\u205f\u3000]', ' ', normalized)
    # Catch-all: replace any remaining non-ASCII punctuation with space
    normalized = ''.join(
        c if ord(c) < 128 else (' ' if unicodedata.category(c) in ('Po', 'Ps', 'Pe', 'Pi', 'Pf') else c)
        for c in normalized
    )
    return normalized

def translate_line(text, translator):
    """Translate text using Google Translate with retry on error"""
    if not text.strip():
        return None

    max_retries = 5
    base_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            translated = translator.translate(text)
            if normalize_text(translated) != normalize_text(text):
                print(f"Translated '{text}' to '{translated}'")
                return translated
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                wait = base_delay * (2 ** attempt)  # exponential backoff: 2, 4, 8, 16s
                print(f"Translation error for '{text}': {e}. Retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"Translation failed for '{text}' after {max_retries} attempts: {e}. Skipping.")
                return None

def line_needs_translation(text: str) -> bool:
    if not text.strip():
        return False

    if is_metadata_line(text):
        return False

    normalized = normalize_punctuation(text)
    
    non_ascii = re.findall(r'[^\x00-\x7F]', normalized)
    if non_ascii:
        print(f"  [non-ascii after normalize] {[(c, hex(ord(c))) for c in non_ascii]}")
    
    return bool(non_ascii)


def needs_translation(lyrics: str) -> bool:
    """
    Check if any lyric line contains non-English text.
    Strips timestamps before checking each line.
    """
    if not lyrics:
        return False

    section_markers = {"chorus", "bridge", "verse", "instrumental", "outro",
                       "interlude", "pre-chorus", "intro", "hook"}

    for raw_line in lyrics.split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Extract first timestamp if present
        ts_match = re.match(r'\[(\d+):(\d+\.\d+)\]', raw_line)
        timestamp_seconds = None
        if ts_match:
            timestamp_seconds = int(ts_match.group(1)) * 60 + float(ts_match.group(2))

        text = re.sub(r'\[\d+:\d+\.\d+\]', '', raw_line).strip()

        if not text or text.lower() in section_markers:
            continue

        if is_metadata_line(text, timestamp_seconds):
            continue

        if line_needs_translation(text):
            print(f"  [flagged] '{text}'")  # <-- temporary debug line
            return True

    return False

def already_translated(lyrics: str) -> bool:
    """Check if lyrics already contain inline translations in parentheses."""
    lines = [re.sub(r'\[\d+:\d+\.\d+\]', '', l).strip() for l in lyrics.split("\n") if l.strip()]
    translated_lines = sum(1 for l in lines if re.match(r'^\(.*\)$', l))
    return translated_lines / max(len(lines), 1) >= 0.2  # 20% of lines are translations

CREDIT_LABELS = {
    '作曲',  # composed by
    '作詞',  # lyrics by
    '作词',  # lyrics by
    '編曲',  # arranged by
    '歌',    # vocals by
    '音楽',  # music by
    '演奏',  # performed by
    '制作',  # produced by
}

def is_metadata_line(text: str, timestamp_seconds: float = None) -> bool:
    """Check if a line is a credits/metadata label"""
    # Normalize fullwidth punctuation to ASCII
    normalized = re.sub(r'[\uff01-\uff60]', lambda m: chr(ord(m.group()) - 0xfee0), text)

    # Lines in the first 2 seconds are typically title/artist headers
    if timestamp_seconds is not None and timestamp_seconds <= 2.0:
        return True

    # CJK text followed by colon and name (e.g. 吉他：Nile Rodgers)
    if re.match(r'^[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+\s*[：:]\s*\S', text):
        return True

    # Known CJK credit keywords
    if any(label in text for label in CREDIT_LABELS):
        return True

    # Common English credit patterns: "Written by:", "Music by:", etc.
    if re.match(r'^(written|composed|lyrics|music|arranged|performed|produced|vocals?)'
                r'\s*(by\s*)?[：:]', normalized, re.IGNORECASE):
        return True

    # LRC tag lines like [ti:...], [ar:...], [al:...], [by:]
    if re.match(r'^\[(ti|ar|al|by|offset|length|re|ve):', text, re.IGNORECASE):
        return True

    return False

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

        if already_translated(lyrics):
            print("Already translated, skipping.")
            continue

        # Print lyrics with non-English lines highlighted in yellow
        print("Lyrics:")
        for raw_line in lyrics.split("\n"):
            text = re.sub(r'\[\d+:\d+\.\d+\]', '', raw_line).strip()
            section_markers = {"chorus", "bridge", "verse", "instrumental", "outro",
                               "interlude", "pre-chorus", "intro", "hook"}
            if text and text.lower() not in section_markers and line_needs_translation(text):
                print(f"\033[33m{raw_line}\033[0m")  # Yellow highlight
            else:
                print(raw_line)

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
    translate_lyrics("/home/adam/driveBig/Music/My Playlist")