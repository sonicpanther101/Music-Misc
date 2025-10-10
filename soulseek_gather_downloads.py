# search all nested files in directory and move them to the root directory
import os
import shutil

def search_files_recursive(directory):
    for root, dirs, files in os.walk(directory):
        for dir in dirs:
            for file in os.listdir(os.path.join(root, dir)):
                yield os.path.join(root, dir, file)

def search_files(directory):
    for file in os.listdir(directory):
        yield os.path.join(directory, file)

def cleanup(directory):
    # delete empty directories
    for root, dirs, files in os.walk(directory):
        for dir in dirs:
            print(dir)
            # check if directory is empty
            if len(os.listdir(os.path.join(root, dir))) == 0:
                os.rmdir(os.path.join(root, dir))

def move_files_to_root(directory, new_directory):
    print(f"moving files from {directory} to {new_directory}")
    root_dir = os.path.dirname(directory)
    for file in search_files_recursive(directory):
        file_name = os.path.basename(file)
        if not file_name.endswith('.flac'):
            continue
        print(file_name)
        new_path = os.path.join(new_directory, file_name)
        print(new_path)
        try:
            shutil.move(file, new_path)
        except:
            shutil.move(file, new_path.replace('.flac', ' (1).flac'))

    cleanup(directory)

if __name__ == "__main__":
    move_files_to_root("C:/Users/Adam/Documents/Soulseek Downloads/complete", "D:/Music/New unformated songs")