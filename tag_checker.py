import os
import sys
from pathlib import Path
from mutagen.flac import FLAC
from PIL import Image
import io
import matplotlib.pyplot as plt

def find_flac_file(directory, search_string):
    """Find the first FLAC file matching the search string."""
    directory = Path(directory)
    
    if not directory.exists():
        print(f"Error: Directory '{directory}' does not exist.")
        return None
    
    # Search for FLAC files containing the search string (case-insensitive)
    for file_path in directory.rglob("*.flac"):
        if search_string.lower() in file_path.name.lower():
            return file_path
    
    print(f"No FLAC file found matching '{search_string}' in '{directory}'")
    return None

def print_tags(flac_file):
    """Extract and print all tags from a FLAC file."""
    audio = FLAC(flac_file)
    
    print("\n" + "="*70)
    print(f"FLAC FILE: {flac_file.name}")
    print("="*70)
    
    print("\n--- AUDIO PROPERTIES ---")
    print(f"Sample Rate: {audio.info.sample_rate} Hz")
    print(f"Channels: {audio.info.channels}")
    print(f"Bits Per Sample: {audio.info.bits_per_sample}")
    print(f"Length: {audio.info.length:.2f} seconds ({audio.info.length/60:.2f} minutes)")
    print(f"Bitrate: {audio.info.bitrate} bps")
    
    print("\n--- METADATA TAGS ---")
    if audio.tags:
        for key, value in sorted(audio.tags.items()):
            print(f"{key}: {value}")
    else:
        print("No tags found.")
    
    return audio

def extract_and_display_images(audio):
    """Extract all images from FLAC file and display them."""
    pictures = audio.pictures
    
    if not pictures:
        print("\n--- IMAGES ---")
        print("No embedded images found.")
        return
    
    print(f"\n--- IMAGES ({len(pictures)} found) ---")
    
    # Create figure with subplots for each image
    num_images = len(pictures)
    cols = min(3, num_images)
    rows = (num_images + cols - 1) // cols
    
    fig, axes = plt.subplots(rows, cols, figsize=(6*cols, 6*rows))
    if num_images == 1:
        axes = [axes]
    else:
        axes = axes.flatten() if num_images > 1 else [axes]
    
    for idx, picture in enumerate(pictures):
        print(f"\nImage {idx + 1}:")
        print(f"  Type: {picture.type} ({get_picture_type_name(picture.type)})")
        print(f"  MIME Type: {picture.mime}")
        print(f"  Description: {picture.desc}")
        print(f"  Size: {len(picture.data)} bytes")
        print(f"  Width: {picture.width}px")
        print(f"  Height: {picture.height}px")
        print(f"  Color Depth: {picture.depth} bits")
        print(f"  Number of Colors: {picture.colors}")
        
        # Load and display image
        try:
            img = Image.open(io.BytesIO(picture.data))
            axes[idx].imshow(img)
            axes[idx].axis('off')
            title = f"{get_picture_type_name(picture.type)}\n{picture.width}x{picture.height}px"
            axes[idx].set_title(title, fontsize=10)
        except Exception as e:
            print(f"  Error loading image: {e}")
            axes[idx].text(0.5, 0.5, f"Error loading image {idx+1}", 
                          ha='center', va='center')
            axes[idx].axis('off')
    
    # Hide any unused subplots
    for idx in range(num_images, len(axes)):
        axes[idx].axis('off')
    
    plt.tight_layout()
    plt.show()

def get_picture_type_name(picture_type):
    """Convert picture type number to descriptive name."""
    types = {
        0: "Other",
        1: "32x32 file icon",
        2: "Other file icon",
        3: "Cover (front)",
        4: "Cover (back)",
        5: "Leaflet page",
        6: "Media",
        7: "Lead artist/lead performer/soloist",
        8: "Artist/performer",
        9: "Conductor",
        10: "Band/Orchestra",
        11: "Composer",
        12: "Lyricist/text writer",
        13: "Recording Location",
        14: "During recording",
        15: "During performance",
        16: "Movie/video screen capture",
        17: "A bright colored fish",
        18: "Illustration",
        19: "Band/artist logotype",
        20: "Publisher/Studio logotype"
    }
    return types.get(picture_type, f"Unknown ({picture_type})")

def main(path=None):
    print("=" * 70)
    print("FLAC File Tag and Image Extractor")
    print("=" * 70)
    
    if path:
        directory = path
    else:
        directory = input("\nEnter the directory path: ").strip()
    search_string = input("Enter the search string: ").strip()
    
    if not directory or not search_string:
        print("\nError: Both directory and search string are required.")
        sys.exit(1)
    
    # Find the first matching FLAC file
    flac_file = find_flac_file(directory, search_string)
    
    if flac_file:
        # Extract and print tags
        audio = print_tags(flac_file)
        
        # Extract and display images
        extract_and_display_images(audio)

if __name__ == "__main__":
    main("C:/Users/Adam/Music/My Playlist")