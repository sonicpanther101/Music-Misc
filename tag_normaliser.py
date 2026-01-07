#!/usr/bin/env python3
"""
FLAC Tag Consistency Checker
Finds inconsistencies in FLAC file tags and allows interactive standardization.
"""

import os
import readline
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
import mutagen
from mutagen.flac import FLAC
from tqdm import tqdm

def get_flac_files(folder_path):
    """Get all FLAC files in the specified folder."""
    print("\nScanning for FLAC files...")
    return list(Path(folder_path).glob("*.flac"))

def extract_tags(flac_files):
    """Extract common tags from FLAC files."""
    tags_data = []
    common_tags = ['artist', 'album', 'albumartist', 'genre', 'date']
    
    print("\nExtracting tags from files...")
    for file_path in tqdm(flac_files, desc="Reading tags", unit="file"):
        try:
            audio = FLAC(file_path)
            file_tags = {'file': file_path.name}
            
            for tag in common_tags:
                if tag in audio:
                    # Get first value if it's a list
                    value = audio[tag][0] if isinstance(audio[tag], list) else audio[tag]
                    file_tags[tag] = value
                else:
                    file_tags[tag] = None
            
            tags_data.append(file_tags)
        except Exception as e:
            tqdm.write(f"Error reading {file_path.name}: {e}")
    
    return tags_data

def similarity(a, b):
    """Calculate similarity ratio between two strings (case-insensitive)."""
    if a is None or b is None:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def are_likely_duplicates(val1, val2):
    """Check if two values are likely the same with minor differences."""
    if val1 == val2:
        return False
    
    # Check if they're identical when case-insensitive
    if val1.lower() == val2.lower():
        return True
    
    # Normalize: remove extra spaces, replace & with 'and', etc.
    def normalize(s):
        import re
        s = re.sub(r'\s+', ' ', s.strip())  # Normalize whitespace
        s = s.replace(' & ', ' and ')  # & vs and
        s = s.replace('&', ' and ')
        return s.lower()
    
    norm1 = normalize(val1)
    norm2 = normalize(val2)
    
    if norm1 == norm2:
        return True
    
    # High similarity check (95%+) - catches typos and minor differences
    sim = similarity(val1, val2)
    if sim >= 0.95:
        return True
    
    return False

def find_inconsistencies(tags_data):
    """Find tags with similar but different values. Returns list of groups."""
    inconsistency_groups = []
    common_tags = ['artist', 'album', 'albumartist', 'genre', 'date']
    
    print("\nAnalyzing tags for inconsistencies...")
    
    for tag in tqdm(common_tags, desc="Analyzing tags", unit="tag"):
        # Group by unique values
        unique_values = {}
        
        for entry in tags_data:
            value = entry.get(tag)
            if value:
                unique_values.setdefault(value, []).append(entry['file'])
        
        # Find similar values that aren't identical
        values_list = list(unique_values.keys())
        
        # Track which values have been grouped together
        grouped = set()
        
        # Use nested progress bar for comparisons if there are many values
        if len(values_list) > 10:
            for i, val1 in enumerate(tqdm(values_list, desc=f"  Comparing {tag}", leave=False)):
                if val1 in grouped:
                    continue
                    
                # Find all values that match this one
                matches = {}
                for j, val2 in enumerate(values_list):
                    if i != j and val2 not in grouped and are_likely_duplicates(val1, val2):
                        if not matches:  # First match, add val1 too
                            matches[val1] = unique_values[val1]
                        matches[val2] = unique_values[val2]
                        grouped.add(val2)
                
                if matches:
                    grouped.add(val1)
                    inconsistency_groups.append({
                        'tag': tag,
                        'variations': matches
                    })
        else:
            for i, val1 in enumerate(values_list):
                if val1 in grouped:
                    continue
                    
                matches = {}
                for j, val2 in enumerate(values_list):
                    if i != j and val2 not in grouped and are_likely_duplicates(val1, val2):
                        if not matches:
                            matches[val1] = unique_values[val1]
                        matches[val2] = unique_values[val2]
                        grouped.add(val2)
                
                if matches:
                    grouped.add(val1)
                    inconsistency_groups.append({
                        'tag': tag,
                        'variations': matches
                    })
    
    return inconsistency_groups

def display_inconsistencies(inconsistency_groups):
    """Display found inconsistencies."""
    if not inconsistency_groups:
        print("\n✓ No tag inconsistencies found!")
        return False
    
    print("\n" + "="*60)
    print(f"FOUND {len(inconsistency_groups)} INCONSISTENCY GROUP(S)")
    print("="*60)
    
    for i, group in enumerate(inconsistency_groups, 1):
        tag = group['tag']
        variations = group['variations']
        print(f"\nGroup {i}: [{tag.upper()}]")
        for value, files in variations.items():
            print(f"  • '{value}' ({len(files)} file(s))")
    
    return True

def choose_standard_value(group_num, total_groups, tag, variations):
    """Let user choose which variant to use as standard."""
    print(f"\n{'='*60}")
    print(f"Group {group_num}/{total_groups} - Choose standard value for: {tag.upper()}")
    print('='*60)
    
    variants = list(variations.keys())
    for i, variant in enumerate(variants, 1):
        count = len(variations[variant])
        print(f"{i}. '{variant}' ({count} file(s))")
        # Show a few example files
        for f in variations[variant][:2]:
            print(f"   └─ {f}")
    
    while True:
        try:
            choice = input(f"\nSelect option (1-{len(variants)}) or 's' to skip: ").strip()
            if choice.lower() == 's':
                return None
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(variants):
                return variants[choice_idx]
            print("Invalid choice. Try again.")
        except (ValueError, IndexError):
            print("Invalid input. Try again.")

def apply_changes(folder_path, tag, standard_value, variations):
    """Apply the standardized tag value to all affected files."""
    files_to_update = []
    
    # Collect all files that need updating (those with different values)
    for value, files in variations.items():
        if value != standard_value:
            files_to_update.extend(files)
    
    if not files_to_update:
        print("No changes needed.")
        return
    
    print(f"\nWill update {len(files_to_update)} file(s):")
    for f in files_to_update[:5]:
        print(f"  - {f}")
    if len(files_to_update) > 5:
        print(f"  ... and {len(files_to_update)-5} more")
    
    confirm = input(f"\nChange '{tag}' to '{standard_value}' in these files? (y/n): ").strip().lower()
    
    if confirm == 'y':
        updated = 0
        print()
        for filename in tqdm(files_to_update, desc="Updating files", unit="file"):
            try:
                file_path = Path(folder_path) / filename
                audio = FLAC(file_path)
                audio[tag] = standard_value
                audio.save()
                updated += 1
            except Exception as e:
                tqdm.write(f"Error updating {filename}: {e}")
        
        print(f"✓ Successfully updated {updated} file(s)!")
    else:
        print("Changes cancelled.")

def normalise(path):
    print("FLAC Tag Consistency Checker")
    print("="*60)
    
    if not path:
        folder_path = input("Enter folder path (or '.' for current directory): ").strip()
        if not folder_path:
            folder_path = '.'
    else:
        folder_path = path
    
    folder_path = Path(folder_path)
    
    if not folder_path.exists():
        print(f"Error: Folder '{folder_path}' does not exist!")
        return
    
    print(f"\nScanning folder: {folder_path.absolute()}")
    
    flac_files = get_flac_files(folder_path)
    
    if not flac_files:
        print("No FLAC files found in the specified folder.")
        return
    
    print(f"Found {len(flac_files)} FLAC file(s)")
    
    tags_data = extract_tags(flac_files)
    
    inconsistency_groups = find_inconsistencies(tags_data)
    
    has_issues = display_inconsistencies(inconsistency_groups)
    
    if not has_issues:
        return
    
    # Interactive fixing
    print("\n" + "="*60)
    print("INTERACTIVE FIX MODE")
    print("="*60)
    
    for i, group in enumerate(inconsistency_groups, 1):
        tag = group['tag']
        variations = group['variations']
        
        standard = choose_standard_value(i, len(inconsistency_groups), tag, variations)
        if standard:
            apply_changes(folder_path, tag, standard, variations)
    
    print("\n✓ All done!")

if __name__ == "__main__":
    try:
        normalise()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\nError: {e}")