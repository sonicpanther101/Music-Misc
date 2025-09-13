# search all nested files in directory and move them to the root directory
import os

def search_files_recursive(directory):
    for root, dirs, files in os.walk(directory):
        for dir in dirs:
            for file in os.listdir(os.path.join(root, dir)):
                yield os.path.join(root, dir, file)

def search_files(directory):
    for file in os.listdir(directory):
        yield os.path.join(directory, file)

def move_files_to_root(directory):
    root_dir = os.path.dirname(directory)
    for file in search_files_recursive(directory):
        file_name = os.path.basename(file)
        if not file_name.endswith('.flac'):
            continue
        print(file_name)
        new_path = os.path.join(root_dir, file_name)
        print(new_path)
        try:
            os.rename(file, new_path)
        except:
            os.rename(file, new_path.replace('.flac', ' (1).flac'))

move_files_to_root("C:/Users/Adam/Documents/Soulseek Downloads/complete")