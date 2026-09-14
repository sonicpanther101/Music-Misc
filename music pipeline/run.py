#!/usr/bin/env python3
"""
run.py - one script to take new downloads from your downloads folder all the
way to a fully tagged, imaged, and correctly named FLAC in your music folder.

Usage:
    python3 run.py            # uses saved settings, asks only what's new
    python3 run.py --setup    # re-run the full Q&A and overwrite saved settings
    python3 run.py --auto     # skip optional stages that weren't already
                               # answered "yes" in a previous --setup, no
                               # re-prompting for toggles (still asks per-file
                               # questions inside stages like fix_tags)

Settings (folders, toggles, your contact email, quality level, etc.) are
saved to ~/.music_pipeline/config.json after the first run, so normally you
just run `python3 run.py` and only get asked the handful of per-song
questions that actually need a human (missing tags, which cover image to
use, etc.) instead of babysitting five separate scripts.

Keep this file in the same folder as the other pipeline scripts - it
imports them directly.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

CONFIG_PATH = Path.home() / ".music_pipeline" / "config.json"

DEFAULT_CONFIG = {
    "download_dir": "",
    "unformatted_dir": "",
    "playlist_dir": "",
    "contact_email": "",
    "flac_quality": 8,
    "remove_original_after_convert": False,
    "downsize_in_place": True,
    "toggles": {
        "translate_lyrics": False,
        "remove_asterisks": True,
        "normalise_tags": True,
        "genre_tags": False,
        "fix_capitalisation": False,
        "musicbrainz_ids": False,
        "downsize": True,
        "lossless_check": False,
        "wait_for_foobar_replaygain": True,
    },
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def ask_yes_no(prompt, default=True):
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        ans = input(prompt + suffix).strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_path(prompt, current=""):
    while True:
        suffix = f" [{current}]: " if current else ": "
        ans = input(prompt + suffix).strip().strip('"')
        path = ans or current
        if not path:
            print("A path is required.")
            continue
        return str(Path(path).expanduser())


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            cfg.update({k: v for k, v in saved.items() if k != "toggles"})
            cfg["toggles"].update(saved.get("toggles", {}))
            return cfg
        except (json.JSONDecodeError, OSError):
            print(f"Warning: couldn't read {CONFIG_PATH}, starting fresh.")
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def run_setup(cfg):
    print("=" * 70)
    print("MUSIC PIPELINE SETUP")
    print("Answer these once - they're saved and reused every future run.")
    print("(Run with --setup any time to change them.)")
    print("=" * 70)

    cfg["download_dir"] = ask_path(
        "Downloads folder (e.g. Soulseek 'complete' folder)", cfg["download_dir"]
    )
    cfg["unformatted_dir"] = ask_path(
        "Staging folder for newly-tagged songs (your 'New unformatted songs')",
        cfg["unformatted_dir"],
    )
    cfg["playlist_dir"] = ask_path(
        "Final music folder (your 'My Playlist' / music library)",
        cfg["playlist_dir"],
    )

    t = cfg["toggles"]
    t["wait_for_foobar_replaygain"] = ask_yes_no(
        "\nDo you set lyrics/ReplayGain in Foobar2000 (or similar) between "
        "tagging and the final move?",
        t["wait_for_foobar_replaygain"],
    )
    t["remove_asterisks"] = ask_yes_no(
        "Scan lyrics for censored (****) words and offer to fix them?",
        t["remove_asterisks"],
    )
    t["translate_lyrics"] = ask_yes_no(
        "Offer to translate non-English lyric lines?", t["translate_lyrics"]
    )
    t["normalise_tags"] = ask_yes_no(
        "Normalise inconsistent tag spellings across your library "
        "(e.g. 'AC/DC' vs 'ACDC')?",
        t["normalise_tags"],
    )
    t["genre_tags"] = ask_yes_no(
        "Fetch GENRE tags from Last.fm? (needs a free Last.fm API key)",
        t["genre_tags"],
    )
    t["fix_capitalisation"] = ask_yes_no(
        "Fix title/artist/album capitalisation against Last.fm?",
        t["fix_capitalisation"],
    )
    t["musicbrainz_ids"] = ask_yes_no(
        "Resolve MusicBrainz artist IDs?", t["musicbrainz_ids"]
    )
    if t["musicbrainz_ids"] and not cfg["contact_email"]:
        cfg["contact_email"] = input(
            "MusicBrainz requires a contact email or URL for their API "
            "User-Agent: "
        ).strip()
    t["downsize"] = ask_yes_no(
        "Downsize any FLACs above 16-bit/44.1kHz down to that standard?",
        t["downsize"],
    )
    if t["downsize"]:
        cfg["downsize_in_place"] = ask_yes_no(
            "  Replace the original file in place (vs. keep both)?",
            cfg["downsize_in_place"],
        )
    t["lossless_check"] = ask_yes_no(
        "Run the transcode/fake-lossless detector at the end?",
        t["lossless_check"],
    )

    q = input(
        f"\nFLAC compression level 0-12 [{cfg['flac_quality']}]: "
    ).strip()
    if q:
        try:
            cfg["flac_quality"] = max(0, min(12, int(q)))
        except ValueError:
            pass
    cfg["remove_original_after_convert"] = ask_yes_no(
        "Delete original (non-FLAC) files after converting to FLAC?",
        cfg["remove_original_after_convert"],
    )

    save_config(cfg)
    print(f"\nSaved settings to {CONFIG_PATH}\n")
    return cfg


def stage(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def try_import(module_name, attr, pip_hint):
    """Import a stage function, skipping the stage with a helpful message
    instead of crashing the whole run if an optional dependency (e.g.
    deep-translator, curl_cffi) isn't installed."""
    try:
        mod = __import__(module_name)
        return getattr(mod, attr)
    except ImportError as e:
        print(f"[skipping - missing dependency: {e}]")
        print(f"  Install with: pip install {pip_hint} --break-system-packages")
        return None


def safe_call(fn, *args, **kwargs):
    """Run a stage, absorbing sys.exit() calls and exceptions from the
    underlying scripts so one bad stage doesn't kill the whole run."""
    try:
        return fn(*args, **kwargs)
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"[stage exited early: code {e.code}]")
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"[stage failed: {e}]")
        if not ask_yes_no("Continue with the rest of the pipeline?", True):
            raise


def ensure_lastfm_key(key_file=None):
    """genre_tagger.py and capitalisation_fixer.py share one encrypted
    Last.fm API key file; set it up interactively the first time it's needed."""
    from genre_tagger import DEFAULT_KEY_FILE
    key_path = Path(key_file).expanduser() if key_file else DEFAULT_KEY_FILE
    if key_path.exists():
        return str(key_path)
    print(
        f"\nNo Last.fm API key found at {key_path}.\n"
        "Get a free key at https://www.last.fm/api/account/create"
    )
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "genre_tagger.py"),
         "--set-api-key", "--key-file", str(key_path)],
        check=False,
    )
    return str(key_path)


def convert_downloads_to_flac(folder, quality, remove_original):
    """Lean, non-interactive FLAC conversion (no per-run prompts) -
    reuses change_to_flac's ffmpeg wrapper, just skips its Q&A."""
    from change_to_flac import get_audio_files, convert_to_flac, is_ffmpeg_available

    if not is_ffmpeg_available():
        print("ffmpeg not found on PATH - skipping conversion. Install ffmpeg "
              "and re-run.")
        return
    files = get_audio_files(folder)
    if not files:
        print("No non-FLAC audio files to convert.")
        return
    print(f"Converting {len(files)} file(s) to FLAC (quality {quality})...")
    ok, failed = 0, 0
    for f in files:
        if convert_to_flac(f, output_folder=None, quality=quality,
                            overwrite=False, remove_original=remove_original):
            ok += 1
        else:
            failed += 1
    print(f"Converted: {ok}  Failed: {failed}")


def downsize_flacs(folder, in_place):
    import shutil as _sh
    if not (_sh.which("ffmpeg") and _sh.which("ffprobe")):
        print("ffmpeg/ffprobe not found - skipping downsize stage.")
        return
    from downsize_music import process_folder
    process_folder(folder, in_place=in_place)


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def main():
    auto = "--auto" in sys.argv
    setup = "--setup" in sys.argv or not CONFIG_PATH.exists()

    cfg = load_config()
    if setup:
        cfg = run_setup(cfg)
    else:
        print(f"Using saved settings from {CONFIG_PATH} (run with --setup to change them).")

    download_dir = cfg["download_dir"]
    unformatted_dir = cfg["unformatted_dir"]
    playlist_dir = cfg["playlist_dir"]
    t = cfg["toggles"]

    for d in (unformatted_dir, playlist_dir):
        os.makedirs(d, exist_ok=True)

    # ---------------- Stage 1: downloads -> staged & tagged FLACs -------
    stage("1/4  Gathering new downloads into the staging folder")
    from soulseek_gather_downloads import move_files_to_root
    safe_call(move_files_to_root, download_dir, unformatted_dir)

    stage("2/4  Converting anything that isn't FLAC yet")
    safe_call(convert_downloads_to_flac, unformatted_dir,
               cfg["flac_quality"], cfg["remove_original_after_convert"])

    stage("3/4  Fixing/filling tags and filenames")
    from fix_tags import fix_tags
    safe_call(fix_tags, unformatted_dir)

    if t["wait_for_foobar_replaygain"]:
        input(
            "\nNow set lyrics + ReplayGain (scan as album) in Foobar2000 "
            "or your tool of choice for the files in:\n  "
            f"{unformatted_dir}\nPress Enter here once that's done..."
        )

    if t["remove_asterisks"]:
        stage("Cleaning censored words out of lyrics")
        fn = try_import("remove_asterixs_from_lyrics", "remove_asterixs_from_lyrics", "colorama")
        if fn:
            safe_call(fn, unformatted_dir)

    if t["translate_lyrics"]:
        stage("Translating non-English lyrics")
        fn = try_import("translate_lyrics", "translate_lyrics", "deep-translator langdetect")
        if fn:
            safe_call(fn, unformatted_dir)

    stage("4/4  Final review and move into your music folder")
    from final_check import confirm_and_move
    safe_call(confirm_and_move, unformatted_dir, playlist_dir)

    # ---------------- Stage 2: library-wide polish -----------------------
    if t["normalise_tags"]:
        stage("Normalising inconsistent tags across the library")
        from tag_normaliser import normalise
        safe_call(normalise, playlist_dir)

    if t["genre_tags"]:
        stage("Fetching genre tags from Last.fm")
        key_file = ensure_lastfm_key()
        subprocess.run([sys.executable, str(SCRIPT_DIR / "genre_tagger.py"),
                         playlist_dir, "--key-file", key_file], check=False)

    if t["fix_capitalisation"]:
        stage("Fixing capitalisation against Last.fm")
        key_file = ensure_lastfm_key()
        subprocess.run([sys.executable, str(SCRIPT_DIR / "capitalisation_fixer.py"),
                         playlist_dir, "--key-file", key_file], check=False)

    if t["musicbrainz_ids"]:
        stage("Resolving MusicBrainz artist IDs")
        contact = cfg["contact_email"] or input(
            "Contact email/URL for MusicBrainz User-Agent: "
        ).strip()
        cfg["contact_email"] = contact
        save_config(cfg)
        subprocess.run([sys.executable, str(SCRIPT_DIR / "musicbrainz_id_finder.py"),
                         playlist_dir, "--contact", contact], check=False)

    stage("Setting cover + artist images (front cover & artist photo only)")
    fn = try_import("image_fixer", "process_library", "Pillow beautifulsoup4 curl_cffi matplotlib")
    if fn:
        safe_call(fn, playlist_dir)

    if t["downsize"]:
        stage("Downsizing any FLACs above 16-bit/44.1kHz")
        safe_call(downsize_flacs, playlist_dir, cfg["downsize_in_place"])

    if t["lossless_check"]:
        stage("Scanning for likely transcodes (fake lossless)")
        subprocess.run([sys.executable, str(SCRIPT_DIR / "lossless_checker.py"),
                         playlist_dir, "--recursive"], check=False)

    print("\n" + "=" * 70)
    print("All done! New songs are formatted, tagged, imaged, and in:")
    print(f"  {playlist_dir}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted - partial progress has already been saved to disk.")
        sys.exit(1)
