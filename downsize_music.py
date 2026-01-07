#!/usr/bin/env python3
"""
FLAC Audio Compressor
Converts FLAC files with higher specs than 16-bit/44.1kHz down to that standard
while preserving all metadata and embedded images.
"""

import os
import readline
import sys
import subprocess
from pathlib import Path

def get_flac_info(file_path):
    """Get bit depth and sample rate of a FLAC file."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=sample_rate,bits_per_raw_sample',
             '-of', 'default=noprint_wrappers=1', str(file_path)],
            capture_output=True,
            text=True,
            check=True
        )

        info = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=')
                info[key] = int(value)
        
        return info.get('bits_per_raw_sample'), info.get('sample_rate')
    except subprocess.CalledProcessError as e:
        print(f"Error reading {file_path}: {e}")
        return None, None

def needs_conversion(bit_depth, sample_rate):
    """Check if file needs conversion."""
    if bit_depth is None or sample_rate is None:
        return False
    return bit_depth > 16 or sample_rate > 44100

def convert_flac(input_path, output_path):
    """Convert FLAC to 16-bit/44.1kHz using ffmpeg."""
    try:
        subprocess.run(
            ['ffmpeg', '-i', str(input_path),
             '-ar', '44100',  # Sample rate
             '-sample_fmt', 's16',  # 16-bit
             '-map_metadata', '0',  # Copy all metadata
             '-map', '0',  # Copy all streams (audio + images)
             '-c:a', 'flac',  # Use FLAC codec
             '-compression_level', '5',  # Compression level (0-12)
             str(output_path)],
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error converting {input_path}: {e.stderr.decode()}")
        return False

def process_folder(folder_path, in_place=False):
    """Process all FLAC files in a folder."""
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"Error: Folder '{folder_path}' does not exist")
        return
    
    flac_files = list(folder.glob('*.flac'))
    
    if not flac_files:
        print(f"No FLAC files found in '{folder_path}'")
        return
    
    print(f"Found {len(flac_files)} FLAC file(s)")
    print(f"Target: 16-bit / 44.1kHz")
    print("-" * 50)
    
    converted_count = 0
    skipped_count = 0
    
    for flac_file in flac_files:
        
        bit_depth, sample_rate = get_flac_info(flac_file)
        
        if bit_depth and sample_rate:
            
            if needs_conversion(bit_depth, sample_rate):
                print(f"\nProcessing: {flac_file.name}")
                print(f"  Current: {bit_depth}-bit / {sample_rate/1000:.1f}kHz")

                # # Ask user to confirm
                # response = input(f"  Convert this file? (y/n/q to quit): ").strip().lower()
                
                # if response == 'q':
                #     print("\nStopping conversion process...")
                #     break
                # elif response != 'y':
                #     print(f"  - Skipped by user")
                #     skipped_count += 1
                #     continue
                
                if in_place:
                    temp_file = flac_file.with_suffix('.tmp.flac')
                    output_file = temp_file
                else:
                    output_file = flac_file.with_stem(f"{flac_file.stem}_16bit_44.1kHz")
                
                print(f"  Converting...")
                
                if convert_flac(flac_file, output_file):
                    if in_place:
                        # Replace original with converted file
                        os.replace(temp_file, flac_file)
                        print(f"  ✓ Converted (replaced original)")
                    else:
                        print(f"  ✓ Converted to: {output_file.name}")
                    converted_count += 1
                else:
                    if in_place and temp_file.exists():
                        temp_file.unlink()
                    print(f"  ✗ Conversion failed")
            else:
                # print(f"  - Already at or below 16-bit/44.1kHz (skipped)")
                skipped_count += 1
        else:
            print(f"  ✗ Could not read file info")
    
    print("\n" + "=" * 50)
    print(f"Converted: {converted_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Total processed: {len(flac_files)}")

def compress_music(path = None):
    print("=" * 50)
    print("FLAC Audio Compressor")
    print("Converts FLAC files to 16-bit/44.1kHz")
    print("=" * 50)
    
    # Check for ffmpeg and ffprobe
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        subprocess.run(['ffprobe', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\nError: ffmpeg and ffprobe are required but not found")
        print("Install with: apt-get install ffmpeg (Linux) or brew install ffmpeg (Mac)")
        sys.exit(1)
    
    # Get folder path
    if path:
        folder_path = path
    else:
        folder_path = input("\nEnter the folder path containing FLAC files: ").strip()
    
    if not folder_path:
        print("Error: No folder path provided")
        sys.exit(1)
    
    # Ask about in-place conversion
    print("\nConversion mode:")
    print("  1. Create new files (keeps originals)")
    print("  2. Replace original files (in-place)")
    
    mode = input("\nSelect mode (1 or 2) [default: 1]: ").strip()
    
    in_place = mode == '2'
    
    if in_place:
        confirm = input("\nWarning: This will replace original files. Continue? (y/n): ")
        if confirm.lower() != 'y':
            print("Cancelled")
            sys.exit(0)
    
    print()
    process_folder(folder_path, in_place)

if __name__ == '__main__':
    compress_music("D:/Music/My Playlist")