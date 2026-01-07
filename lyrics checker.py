import os
import readline
from mutagen.flac import FLAC

songExclusions = [
    ["Blink-182", "The Fallen Interlude"],
    ["Blink-182", "Fuck Face"],
    ["Car Seat Headrest", "Stop Smoking"],
    ["DIIV", "Home"],

]

def check_time_sync(folder_path):
    for file_path in os.listdir(folder_path):
        if file_path.endswith(".flac"):
            file_path = os.path.join(folder_path, file_path)
            audio = FLAC(file_path)
            if 'lyrics' in audio:
                lines = audio['lyrics'][0].split('\n')
                timestamps = 0
                for line in lines:
                    if '[?]' in line:
                        # print the artist, title, album and the line plus the 3 lines before  and after it
                        artist = audio['artist'][0][:30]
                        title = audio['title'][0][:30]
                        album = audio['album'][0][:30]
                        print("Lyrics with ? in it")
                        print(f"{artist:30} {title:30} {album:30}")
                        for i in range(-3, 4):
                            if len(lines) > i + lines.index(line):
                                if lines[i + lines.index(line)]:
                                    print(f"{lines[i + lines.index(line)]}")
                    if '[' in line:
                        if ':' in line:
                            timestamps += 1
                    if '纯音乐，请欣赏' in line:
                        timestamps = -100
                if timestamps < 5:
                    # print the artist, title, album in columns

                    if "instrumental" in audio:
                        if audio["instrumental"][0] == "1":
                            continue
                    
                    artists = [s[0] for s in songExclusions]
                    titles = [s[1] for s in songExclusions]
                    if any(s in audio["title"][0] for s in titles) and any(s in audio["artist"][0] for s in artists):
                        continue

                    artist = audio['artist'][0][:30]
                    title = audio['title'][0][:30]
                    album = audio['album'][0][:30]
                    print(f"{artist:30} {title:30} {album:30}")
            else:
                if "instrumental" in audio:
                    if audio["instrumental"][0] == "1":
                        continue

                artists = [s[0] for s in songExclusions]
                titles = [s[1] for s in songExclusions]
                if any(s in audio["title"][0] for s in titles) and any(s in audio["artist"][0] for s in artists):
                    continue
                
                # print the artist, title, album in columns
                artist = audio['artist'][0][:30]
                title = audio['title'][0][:30]
                album = audio['album'][0][:30]
                print(f"{"":90}{artist:30} {title:30} {album:30}")

if __name__ == "__main__":
    folder_path = "D:/Music/My Playlist" # input("Enter the path to the folder: ")

    check_time_sync(folder_path)