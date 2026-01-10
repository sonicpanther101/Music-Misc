import os
import readline
import sys
from mutagen import File
from mutagen.flac import FLAC
from colorama import Fore, Style, init

# Initialize colorama for cross-platform terminal colors
init(autoreset=True)

songs = []

def find_lyrics_with_star(directory):
    """Scan audio files for lyrics containing '*' and print matching titles."""
    found_songs = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            
            try:
                # Process FLAC files
                if file.lower().endswith('.flac'):
                    audio = FLAC(file_path)
                    if 'lyrics' in audio:
                        lyrics = audio['lyrics'][0].replace('\r', '')
                        if '*' in lyrics:
                            title = audio.get('title', [file])[0]
                            found_songs.append({
                                "title": title,
                                "path": file_path,
                                "original_lyrics": lyrics,
                                "lines": [],
                                "audio": audio
                            })
                            print(f"{Fore.CYAN}Found: {title}")
            
            except Exception as e:
                print(f"{Fore.RED}Error processing {file_path}: {str(e)}", file=sys.stderr)
    return found_songs

def replacements(string):
    fixes = {
        "*************": "motherfuckers",
        "************": "motherfucker",
        "m********e" : "masterbate",
        "m*******a": "marijuana",
        "********": "bullshit",
        "b******t": "bullshit",
        "*******": "fucking",
        "******'": "fuckin'",
        "****in'": "fuckin'",
        "****ing": "fucking",
        "f***ing": "fucking",
        "coc*ine": "cocaine",
        "c*****e": "cocaine",
        "a*****e": "asshole",
        "a**hole": "asshole",
        "****ed": "fucked",
        "******": "fucked",
        "*****y": "bitchy",
        "n***er": "nigger",
        "h****n": "heroin",
        "h***n": "heroin",
        "*****": "bitch",
        "b***h": "bitch",
        "b**th": "bitch",
        "b**ch": "bitch",
        "b*tch": "bitch",
        "B***h": "Bitch",
        "B**ch": "Bitch",
        "B*tch": "Bitch",
        "p***s": "penis",
        "w***e": "whore",
        "n***a": "nigga",
        "n**ga": "nigga",
        "p***y": "pussy",
        "p**sy": "pussy",
        "P**sy": "Pussy",
        "P*ssy": "Pussy",
        "p*ssy": "pussy",
        "h***a": "hella",
        "s***t": "shit",
        "f*ck": "fuck",
        "f***": "fuck",
        "f**k": "fuck",
        "F**k": "Fuck",
        "F**K": "FUCK",
        # "****": "shit",
        "s**t": "shit",
        "sh*t": "shit",
        "Sh*t": "Shit",
        "S**t": "Shit",
        "S**T": "SHIT",
        "h**l": "hell",
        "d**k": "dick",
        "D**n": "Damn",
        "d**n": "damn",
        "d*mn": "damn",
        "d*pe": "dope",
        "d**e": "dope",
        "D**e": "Dope",
        "D**E": "DOPE",
        "d**g": "drug",
        "dr*g": "drug",
        "c**k": "cock",
        "c*ck": "cock",
        "p**n": "porn",
        "p*rn": "porn",
        "a***": "arse",
        "H*p*": "Hump",
        "h**s": "hoes",
        "h*e": "hoe",
        "s*x": "sex",
        # "***": "sex",
        "a**": "ass",
        "A**": "Ass",
        "a*s": "ass"
    }
    for pattern, replacement in fixes.items():
        string = string.replace(pattern, replacement)
    return string

def save_with_retry(audio, path, max_retries=3, retry_delay=2):
    """Attempt to save the audio file with retries if the file is locked."""
    for attempt in range(max_retries):
        try:
            audio.save()
            print(f"{Fore.GREEN}Successfully saved changes!")
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                print(f"{Fore.YELLOW}File is locked (possibly open in media player). Retrying in {retry_delay} seconds...")
                print(f"{Fore.YELLOW}Please close the file in your media player and wait...")
                time.sleep(retry_delay)
            else:
                print(f"{Fore.RED}Failed to save: File is still locked after {max_retries} attempts")
                print(f"{Fore.RED}Please close '{path}' in your media player and try again")
                return False
        except Exception as e:
            print(f"{Fore.RED}Error saving file: {str(e)}")
            return False
    return False

def process_auto_replacement(song):
    """Process a song with interactive approval for known patterns"""
    print(f"\n{Fore.CYAN}===== Automatic Replacement: {song['title']} =====")
    
    # Split lyrics into lines and identify lines with asterisks
    lines = song['original_lyrics'].split('\n')
    changed_lines = []
    
    for i, line in enumerate(lines):
        if '*' in line:
            fixed_line = replacements(line)
            if fixed_line != line:
                changed_lines.append({
                    "index": i,
                    "original": line,
                    "fixed": fixed_line,
                    "approved": False
                })
    
    if not changed_lines:
        print(f"{Fore.YELLOW}No fixable patterns found in lyrics")
        return False
    
    print(f"{Fore.YELLOW}Found {len(changed_lines)} lines with fixable patterns:")
    
    # Process each change with approval
    for change in changed_lines:
        print(f"\n{Fore.WHITE}----- Line {change['index']+1} -----")
        print(f"{Fore.RED}Original: {change['original']}")
        print(f"{Fore.GREEN}Fixed   : {change['fixed']}")
        
        while True:
            response = input(f"Apply this change? ({Fore.GREEN}y{Style.RESET_ALL}/{Fore.RED}n{Style.RESET_ALL}): ").strip().lower()
            if response in ['y', 'n']:
                change['approved'] = (response == 'y')
                break
            print(f"{Fore.YELLOW}Please enter 'y' or 'n'")
    
    # Apply approved changes to the lyrics
    new_lyrics = lines.copy()
    applied_changes = 0
    
    for change in changed_lines:
        if change['approved']:
            new_lyrics[change['index']] = change['fixed']
            applied_changes += 1
    
    # Update the file if changes were approved
    if applied_changes > 0:
        print(f"\n{Fore.YELLOW}Applying {applied_changes} changes to file...")
        
        # Join the modified lyrics back into a single string
        song['audio']['lyrics'] = '\n'.join(new_lyrics)
        
        return save_with_retry(song['audio'], song['path'])
    else:
        print(f"{Fore.YELLOW}No changes applied")
        return False

def process_manual_replacement(song):
    """Manual replacement phase for remaining asterisks"""
    print(f"\n{Fore.CYAN}===== Manual Replacement: {song['title']} =====")
    print(f"{Fore.BLUE}File: {song['path']}")

    # Reload the audio file to get the latest version
    try:
        song['audio'] = FLAC(song['path'])
    except Exception as e:
        print(f"{Fore.RED}Error reloading file: {str(e)}")
        return
    
    # Get current lyrics (might have been modified in auto phase)
    current_lyrics = song['audio'].get('lyrics', [''])[0].replace('\r', '')
    lines = current_lyrics.split('\n')
    
    # Find lines with remaining asterisks
    asterisk_lines = []
    for i, line in enumerate(lines):
        if '*' in line:
            asterisk_lines.append({"index": i, "line": line})
    
    if not asterisk_lines:
        print(f"{Fore.GREEN}No remaining asterisks found")
        return
    
    print(f"{Fore.YELLOW}Found {len(asterisk_lines)} lines with remaining asterisks:")
    
    # Process each line with asterisks
    for entry in asterisk_lines:
        i = entry["index"]
        line = entry["line"]
        
        print(f"\n{Fore.WHITE}----- Line {i+1} -----")
        print(f"{Fore.RED}Current: {line}")
        
        while True:
            try:
                # Ask for replacement text
                replacement = input(f"Enter replacement text (or press Enter to skip): ")
                
                if not replacement:
                    print(f"{Fore.YELLOW}Skipping this line")
                    break
                
                # Show preview
                print(f"\n{Fore.WHITE}Preview:")
                print(f"{Fore.RED}Original: {line}")
                print(f"{Fore.GREEN}Replaced: {replacement}")
                
                # Get confirmation
                confirm = input(f"Confirm replacement? ({Fore.GREEN}y{Style.RESET_ALL}/{Fore.RED}n{Style.RESET_ALL}): ").strip().lower()
                if confirm == 'y':
                    # Apply replacement
                    lines[i] = replacement
                    
                    # Update lyrics in memory
                    song['audio']['lyrics'] = '\n'.join(lines)
                    
                    # Save to file with retry logic
                    if save_with_retry(song['audio'], song['path']):
                        break
                    else:
                        # If save failed, ask if user wants to try again
                        retry = input(f"{Fore.YELLOW}Retry saving? ({Fore.GREEN}y{Style.RESET_ALL}/{Fore.RED}n{Style.RESET_ALL}): ").strip().lower()
                        if retry != 'y':
                            print(f"{Fore.RED}Changes not saved. Moving to next line.")
                            break
                elif confirm == 'n':
                    print(f"{Fore.YELLOW}Replacement discarded")
                    break
                else:
                    print(f"{Fore.YELLOW}Please enter 'y' or 'n'")
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}Skipping this line")
                break
            except Exception as e:
                print(f"{Fore.RED}Error: {str(e)}")

def remove_asterixs_from_lyrics(directory=None):
    if directory is None:
        target_dir = input("Enter the path to the target directory: ")
    else:
        target_dir = directory
        
    if not os.path.isdir(target_dir):
        print(f"{Fore.RED}Error: {target_dir} is not a valid directory")
        sys.exit(1)
    
    # Phase 1: Initial scan
    print(f"{Fore.BLUE}\n===== Phase 1: Initial Scan =====")
    global songs
    songs = find_lyrics_with_star(target_dir)
    
    if not songs:
        print(f"{Fore.YELLOW}No songs with lyrics containing '*' found")
        return
    
    print(f"\n{Fore.GREEN}Found {len(songs)} songs with lyrics containing '*'")
    
    # Phase 2: Automatic replacement
    print(f"{Fore.BLUE}\n===== Phase 2: Automatic Replacement =====")
    for i, song in enumerate(songs):
        print(f"\n{Fore.YELLOW}=== Song {i+1} of {len(songs)} ===")
        process_auto_replacement(song)
    
    # Phase 3: Rescan for remaining asterisks
    print(f"{Fore.BLUE}\n===== Phase 3: Rescan for Remaining Asterisks =====")
    songs = find_lyrics_with_star(target_dir)
    
    if not songs:
        print(f"{Fore.GREEN}No remaining asterisks found!")
        return
    
    print(f"\n{Fore.YELLOW}Found {len(songs)} songs with remaining asterisks")
    
    # Phase 4: Manual replacement
    print(f"{Fore.BLUE}\n===== Phase 4: Manual Replacement =====")
    for i, song in enumerate(songs):
        print(f"\n{Fore.YELLOW}=== Song {i+1} of {len(songs)} ===")
        process_manual_replacement(song)
    
    print(f"\n{Fore.GREEN}Processing complete!")

if __name__ == "__main__":
    remove_asterixs_from_lyrics()