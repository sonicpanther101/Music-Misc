#!/usr/bin/env python3
"""
Interactive Music to FLAC Converter
Converts all non-FLAC music files in a given folder to FLAC format using ffmpeg.
Run the script and input values interactively.
"""

import os
import subprocess
from pathlib import Path

# Supported audio file extensions
AUDIO_EXTENSIONS = {'.mp3', '.mp4', '.m4a', '.aac', '.ogg', '.wav', '.wma', '.opus', '.aiff', '.ape', '.mpc'}

def is_ffmpeg_available():
    """Check if ffmpeg is available in the system PATH."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_audio_files(folder_path):
    """Get all audio files in the folder that are not already FLAC."""
    audio_files = []
    folder = Path(folder_path)
    
    if not folder.exists():
        raise FileNotFoundError(f"Folder '{folder_path}' does not exist")
    
    if not folder.is_dir():
        raise NotADirectoryError(f"'{folder_path}' is not a directory")
    
    for file_path in folder.iterdir():
        if file_path.is_file():
            if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(file_path)
    
    return audio_files

def convert_to_flac(input_file, output_folder=None, quality=8, overwrite=False, remove_original=False):
    """
    Convert an audio file to FLAC format using ffmpeg.
    
    Args:
        input_file: Path to the input audio file
        output_folder: Folder to save the FLAC file (default: same as input)
        quality: FLAC compression level (0-12, default: 8)
        overwrite: Whether to overwrite existing FLAC files
        remove_original: Whether to delete the original file after successful conversion
    """
    input_path = Path(input_file)
    
    if output_folder:
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = input_path.parent
    
    output_file = output_dir / f"{input_path.stem}.flac"
    
    # Check if output file already exists
    if output_file.exists() and not overwrite:
        print(f"Skipping '{input_path.name}' - FLAC file already exists")
        if remove_original:
            try:
                input_path.unlink()
                print(f"  ✓ Removed original file: {input_path.name}")
            except Exception as e:
                print(f"  ✗ Failed to remove original file: {e}")
        return False
    
    # Build ffmpeg command
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-c:a', 'flac',
        '-compression_level', str(quality),
        '-map_metadata', '0',  # Copy metadata
        '-y' if overwrite else '-n',  # Overwrite or skip if exists
        str(output_file)
    ]
    
    try:
        print(f"Converting: {input_path.name} -> {output_file.name}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✓ Successfully converted: {input_path.name}")
        
        # Remove original file if requested and conversion was successful
        if remove_original:
            try:
                input_path.unlink()
                print(f"  ✓ Removed original file: {input_path.name}")
            except Exception as e:
                print(f"  ✗ Failed to remove original file: {e}")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to convert {input_path.name}: {e.stderr}")
        return False

def get_user_input(location = ""):
    """Get user input for conversion settings."""
    print("=" * 60)
    print("           MUSIC TO FLAC CONVERTER")
    print("=" * 60)
    
    # Get folder path
    while True:
        if location:
            folder = location
            break
        folder = input("\nEnter the folder path containing music files: ").strip() # "C:\\Users\\Adam\\Music\\New unformated songs"
        if folder:
            if folder.startswith('"') and folder.endswith('"'):
                folder = folder[1:-1]  # Remove quotes if present
            try:
                Path(folder).resolve()
                break
            except Exception:
                print("Invalid path format. Please try again.")
        else:
            print("Please enter a folder path.")
    
    # Get output folder (optional)
    output_folder = input("Enter output folder (press Enter for same folder): ").strip()
    if output_folder:
        if output_folder.startswith('"') and output_folder.endswith('"'):
            output_folder = output_folder[1:-1]  # Remove quotes if present
    else:
        output_folder = None
    
    # Get quality level
    while True:
        quality_input = input("Enter FLAC compression level (0-12, default 8): ").strip()
        if not quality_input:
            quality = 8
            break
        try:
            quality = int(quality_input)
            if 0 <= quality <= 12:
                break
            else:
                print("Quality must be between 0 and 12.")
        except ValueError:
            print("Please enter a valid number.")
    
    # Ask about overwriting
    while True:
        overwrite_input = input("Overwrite existing FLAC files? (y/N): ").strip().lower()
        if overwrite_input in ['', 'n', 'no']:
            overwrite = False
            break
        elif overwrite_input in ['y', 'yes']:
            overwrite = True
            break
        else:
            print("Please enter 'y' for yes or 'n' for no.")
    
    # Ask about removing original files
    print("\n⚠️  WARNING: This will permanently delete the original files after conversion!")
    while True:
        remove_input = input("Remove original files after successful conversion? (y/N): ").strip().lower()
        if remove_input in ['', 'n', 'no']:
            remove_original = False
            break
        elif remove_input in ['y', 'yes']:
            print("⚠️  Are you sure? Original files will be PERMANENTLY DELETED!")
            confirm = input("Type 'DELETE' to confirm: ").strip()
            if confirm == 'DELETE':
                remove_original = True
                break
            else:
                print("Original files will be kept.")
                remove_original = False
                break
        else:
            print("Please enter 'y' for yes or 'n' for no.")
    
    # Ask about dry run
    while True:
        dry_run_input = input("Do a dry run (preview only)? (y/N): ").strip().lower()
        if dry_run_input in ['', 'n', 'no']:
            dry_run = False
            break
        elif dry_run_input in ['y', 'yes']:
            dry_run = True
            break
        else:
            print("Please enter 'y' for yes or 'n' for no.")
    
    return folder, output_folder, quality, overwrite, remove_original, dry_run

def convert(location = None):

    if not location:
        location = input("Enter folder path: ").strip()
        if not os.path.isdir(location):
            print("Invalid folder.")
            return

    # check that there are non-flac files in the folder
    audio_files = get_audio_files(location)
    if not audio_files:
        print("No non-FLAC files found in the folder.")
        return


    print("Welcome to the Interactive Music to FLAC Converter!")
    
    # Check if ffmpeg is available
    if not is_ffmpeg_available():
        print("\nError: ffmpeg is not available. Please install ffmpeg and ensure it's in your PATH.")
        input("Press Enter to exit...")
        return 1
    
    try:
        # Get user input
        folder, output_folder, quality, overwrite, remove_original, dry_run = get_user_input(location)
        
        print(f"\n{'='*60}")
        print("CONVERSION SETTINGS:")
        print(f"Input folder: {folder}")
        print(f"Output folder: {output_folder if output_folder else 'Same as input'}")
        print(f"Quality level: {quality}")
        print(f"Overwrite existing: {'Yes' if overwrite else 'No'}")
        print(f"Remove original files: {'Yes' if remove_original else 'No'}")
        print(f"Dry run: {'Yes' if dry_run else 'No'}")
        print(f"{'='*60}")
        
        # Get all audio files in the folder
        audio_files = get_audio_files(folder)
        
        if not audio_files:
            print(f"\nNo audio files found in '{folder}'")
            input("Press Enter to exit...")
            return 0
        
        print(f"\nFound {len(audio_files)} audio file(s) to convert:")
        for file in audio_files:
            print(f"  - {file.name}")
        
        if dry_run:
            print(f"\nDry run preview:")
            print(f"- Would convert {len(audio_files)} file(s) to FLAC")
            if remove_original:
                print("- Would DELETE original files after conversion")
            else:
                print("- Would keep original files")
            print("\nRun again without dry run to perform actual conversion.")
            input("Press Enter to exit...")
            return 0
        
        # Confirm before starting
        print(f"\nReady to convert {len(audio_files)} file(s).")
        if remove_original:
            print("⚠️  WARNING: Original files will be PERMANENTLY DELETED after conversion!")
        confirm = input("Do you want to proceed? (Y/n): ").strip().lower()
        if confirm in ['n', 'no']:
            print("Conversion cancelled.")
            input("Press Enter to exit...")
            return 0
        
        print(f"\nStarting conversion...")
        print("-" * 50)
        
        successful = 0
        failed = 0
        removed = 0
        
        for audio_file in audio_files:
            if convert_to_flac(audio_file, output_folder, quality, overwrite, remove_original):
                successful += 1
                if remove_original:
                    removed += 1
            else:
                failed += 1
        
        print("-" * 50)
        print(f"Conversion complete!")
        print(f"✓ Successful: {successful}")
        print(f"✗ Failed: {failed}")
        if remove_original:
            print(f"🗑️  Original files removed: {removed}")
        
        input("\nPress Enter to exit file converter...")
        return 0 if failed == 0 else 1
        
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"\nError: {e}")
        input("Press Enter to exit...")
        return 1
    except KeyboardInterrupt:
        print("\nConversion interrupted by user")
        input("Press Enter to exit...")
        return 1
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        input("Press Enter to exit...")
        return 1

if __name__ == "__main__":
    exit(convert())