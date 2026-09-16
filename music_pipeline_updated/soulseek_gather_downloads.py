# search all nested files in directory and move them to the root directory
import os
import readline
import shutil

# Any file mutagen/ffmpeg later needs to see. Anything not in this set
# (nfo, jpg, txt, m3u, etc. that torrent/soulseek clients dump alongside
# the audio) is left behind in the downloads folder on purpose.
AUDIO_EXTENSIONS = {
    '.flac', '.mp3', '.mp4', '.m4a', '.aac', '.ogg', '.wav',
    '.wma', '.opus', '.aiff', '.ape', '.mpc'
}

def search_files_recursive(directory):
    """Yield every file anywhere under `directory`, including ones sitting
    directly in the top-level folder (not just inside subfolders)."""
    for root, dirs, files in os.walk(directory):
        for file in files:
            yield os.path.join(root, file)

def cleanup(directory):
    """Delete now-empty directories, deepest first, without deleting `directory` itself."""
    for root, dirs, files in os.walk(directory, topdown=False):
        if root == str(directory):
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
                print(f"Removed empty folder: {root}")
        except OSError:
            pass

def move_files_to_root(directory, new_directory):
    print(f"Moving audio files from {directory} to {new_directory}")
    os.makedirs(new_directory, exist_ok=True)
    moved = 0
    for file in search_files_recursive(directory):
        file_name = os.path.basename(file)
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in AUDIO_EXTENSIONS:
            continue
        new_path = os.path.join(new_directory, file_name)
        if os.path.abspath(file) == os.path.abspath(new_path):
            continue
        print(f"  {file_name}")
        try:
            shutil.move(file, new_path)
            moved += 1
        except shutil.Error:
            stem, ext = os.path.splitext(new_path)
            n = 1
            alt_path = f"{stem} ({n}){ext}"
            while os.path.exists(alt_path):
                n += 1
                alt_path = f"{stem} ({n}){ext}"
            shutil.move(file, alt_path)
            moved += 1

    cleanup(directory)
    print(f"Moved {moved} audio file(s).")
    return moved

if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else input("Downloads folder: ").strip()
    dst = sys.argv[2] if len(sys.argv) > 2 else input("Destination folder: ").strip()
    move_files_to_root(src, dst)
