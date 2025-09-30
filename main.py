from soulseek_gather_downloads import move_files_to_root
from change_to_flac import convert
from remove_asterixs_from_lyrics import remove_asterixs_from_lyrics
from fix_tags import fix_tags
from final_check import confirm_and_move

initial_location = "C:/Users/Adam/Documents/Soulseek Downloads/complete"
location = "D:/Music/New unformated songs"
playlist = "D:/Music/My Playlist"

move_files_to_root(initial_location, location)

convert(location)

fix_tags(location)

print("Get lyrics and set replaygain from Foobar2000")
input("Press Enter to continue...")

remove_asterixs_from_lyrics(location)

confirm_and_move(location, playlist)