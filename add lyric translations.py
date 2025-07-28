import mutagen
from mutagen.flac import FLAC
import os

# uses musixmatch lyrics

files = os.listdir("C:/Users/adam/music/my playlist")

def get_unsynced_lyrics(file_path: str) -> str:
    try:
        audio = FLAC(file_path)
        return audio.get("UNSYNCED LYRICS", [""])[0]
    except mutagen.MutagenError as e:
        print(f"Error retrieving lyrics: {e}")
        return ""

def main():
    file = input("Enter the name of the file: ")
    if not file in files:
        print("File not found!")
        return
    
    print("File found!")
    file_path = os.path.join("C:/Users/adam/music/my playlist", file)
    lyrics = get_unsynced_lyrics(file_path)
    print("Lyrics:\n", lyrics)

    print("Enter the lyrics with translation (end with 'end'):")
    english_lines = []
    while True:
        line = input()
        if line.strip() == "end":
            break
        elif line.strip() == "chorus" or line.strip() == "bridge" or line.strip() == "verse" or line.strip() == "instrumental" or line.strip() == "outro" or line.strip() == "interlude" or line.strip() == "pre-chorus" or line.strip() == "intro" or line.strip() == "hook":
            continue
        english_lines.append(line)
    english = english_lines[1::2]
    other = english_lines[::2]

    if not english:
        print("Lyrics not provided.")
        return

    fixed = []

    for i, line in enumerate(lyrics.split("\n")):
        if line.strip() == "":
            continue
        # check if line only contains the time
        if "]" in line and line.strip().endswith("]"):
            print("ooooooooooooooooooooooooooooo")
            fixed.append(line)
            continue

        time = line.split("]")[0]
        other_lang = other[i]
        translated = english[i]

        fixed.append(f"{time}] {other_lang}\n{time}] ({translated})")

    # sort fixed by time
    fixed.sort(key=lambda x: x.split("]")[0])

    fixed_lyrics = "\n".join(fixed)
    print("Fixed lyrics:\n", fixed_lyrics)

    # print if there is a difference in number of lines, ignoring translated

    test = [line for line in fixed if (not line.split("]")[1].strip().startswith("(") and not line.strip().endswith(")"))]
    if len(test) != len(lyrics.split("\n")):
        print("Number of lines is different!")
        print(f"Original: {len(lyrics.split('\n'))}")
        print(f"Fixed: {len(test)}")

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

