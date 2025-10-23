from soulseek_gather_downloads import move_files_to_root
from change_to_flac import convert
from remove_asterixs_from_lyrics import remove_asterixs_from_lyrics
from fix_tags import fix_tags
from artist_image import get_artist_image
from translate_lyrics import translate_lyrics
from final_check import confirm_and_move
from tag_normaliser import normalise
from copy_lyrics import copy_lyrics
from artist_image import get_artist_image
from check_images import process_album_covers
from image_normaliser import normalise_images
from fix_3_images import fix_3_images

def main():
    initial_location = "C:/Users/Adam/Documents/Soulseek Downloads/complete"
    location = "D:/Music/New unformated songs"
    playlist = "D:/Music/My Playlist"


    print("Moving files to root")
    move_files_to_root(initial_location, location)
    print("Converting to FLAC")
    convert(location)
    print("Fixing tags")
    fix_tags(location)

    print("Get lyrics and set replaygain from Foobar2000")
    input("Press Enter to continue...")

    remove_asterixs_from_lyrics(location)
    
    # Ask user if they want to translate lyrics
    translate_choice = input("Do you want to translate non-English lyrics? (y/n): ").lower()
    if translate_choice == 'y':
        translate_lyrics(location)

    confirm_and_move(location, playlist)

    if input("Do you want to normalise tags? (y/n): ").lower() == "y":
        normalise(playlist)
        
    copy_lyrics(playlist)

    print("Getting artist images")
    get_artist_image(playlist)

    normalise_images(playlist)

    process_album_covers(playlist)

    fix_3_images(playlist)

    print("All done!")

if __name__ == "__main__":
    main()