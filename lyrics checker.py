import os
from mutagen.flac import FLAC

intsrumentals = [
    "(Guitar)",
    "(Piano)",
    "A New Beginning",
    "At Doom's Gate (Doom E1M1)",
    "Cat Vibing To Ievan Polkka Swing",
    "Crab Rave",
    "Cyberpunk 2077 Theme Song",
    "Eternal Youth",
    "Gats",
    "Glitz At The Ritz",
    "Intro",
    "Leyenda (Isaac Albeniz)",
    "MEGALOVANIA",
    "Misirlou",
    "Surf Rider",
    "The Only Thing They Fear Is You",
    "The Party Troll",
    "Bustin' Surfboards",
    "For Fra",
    "Aluminum",
    "The Fallen Interlude",
    "Fuck Face",
    "Patience",
    "Pretty Little Ditty",
    "Stop Smoking",
    "Druun",
    "Asteroid Blues"
]

intsrumentalArtists = [
    "C418",
    "F-777",
    "Marcin",
    "Antonio Vivaldi",
    "Bernth",
    "Ptasinski",
    "Mo Beats",
    "Darude",
    "The Revels"
]

intsrumentalSongs = [
  ["The Offspring", "Welcome"]
]

def check_time_sync(folder_path):
    for file_path in os.listdir(folder_path):
        if file_path.endswith(".flac"):
            file_path = os.path.join(folder_path, file_path)
            audio = FLAC(file_path)
            if 'UNSYNCED LYRICS' in audio:
                lines = audio['UNSYNCED LYRICS'][0].split('\n')
                timestamps = 0
                for line in lines:
                    if '[' in line:
                        timestamps += 1
                if timestamps < 5:
                    # print the artist, title, album in columns
                    if any(s in audio["title"][0] for s in intsrumentals):
                        continue

                    if any(s in audio["artist"][0] for s in intsrumentalArtists):
                        continue
                    
                    artists = [s[0] for s in intsrumentalSongs]
                    titles = [s[1] for s in intsrumentalSongs]
                    if any(s in audio["title"][0] for s in titles) and any(s in audio["artist"][0] for s in artists):
                        continue

                    artist = audio['artist'][0][:30]
                    title = audio['title'][0][:30]
                    album = audio['album'][0][:30]
                    print(f"{artist:30} {title:30} {album:30}")
            else:
                if any(s in audio["artist"][0] for s in intsrumentalArtists):
                    continue

                if any(s in audio["title"][0] for s in intsrumentals):
                    continue
                
                # print the artist, title, album in columns
                artist = audio['artist'][0][:30]
                title = audio['title'][0][:30]
                album = audio['album'][0][:30]
                print(f"{"":90}{artist:30} {title:30} {album:30}")

if __name__ == "__main__":
    folder_path = "D:/Music/My Playlist" # input("Enter the path to the folder: ")

    check_time_sync(folder_path)