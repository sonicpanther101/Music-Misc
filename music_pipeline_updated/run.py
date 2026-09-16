#!/usr/bin/env python3
"""
run.py - one script to take new downloads from your downloads folder all the
way to a fully tagged, imaged, ReplayGained, lyriced FLAC in your music
folder - no Foobar/TagScanner/etc. hand-off required.

Usage:
    python3 run.py            # uses saved settings, asks only what's new
    python3 run.py --setup    # re-run the full Q&A and overwrite saved settings
    python3 run.py --auto     # never prompt for setup even if the config is
                               # missing/incomplete - just use defaults for
                               # anything unset (handy for cron/TUI use)

Settings (folders, toggles, your contact email, quality level, etc.) are
saved to ~/.music_pipeline/config.json after the first run, so normally you
just run `python3 run.py` and only get asked the handful of per-song
questions that actually need a human (missing tags, which cover image to
use, "is this really a low-lyrics song?", etc.) instead of babysitting a
pile of separate scripts and other apps.

Two folders are all that's required:
  - download_dir: where new songs land (e.g. your Soulseek "complete" folder)
  - music_dir:    your actual music library

By default everything happens directly in music_dir (source and
destination are the same folder for the tagging/fixing/ReplayGain/lyrics
stages - that's supported end to end, not just tolerated). If you'd rather
review new songs in a separate holding folder before they mix in with your
library, turn on "use a staging folder" during setup and a third folder is
used for the fix-up steps, with a final move into music_dir at the end.

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
    "music_dir": "",
    "use_staging_dir": False,
    "staging_dir": "",
    "contact_email": "",
    "flac_quality": 8,
    "remove_original_after_convert": False,
    "downsize_in_place": True,
    "toggles": {
        "fetch_replaygain": True,
        "fetch_lyrics": True,
        "review_lyrics_gaps": True,
        "remove_asterisks": True,
        "translate_lyrics": False,
        "normalise_tags": True,
        "genre_tags": False,
        "fix_capitalisation": False,
        "musicbrainz_ids": False,
        "downsize": True,
        "lossless_check": False,
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


def _migrate(saved):
    """Bring an old-style config (download_dir/unformatted_dir/playlist_dir,
    wait_for_foobar_replaygain) forward to the current two-folder shape,
    so nobody's saved settings get silently dropped by this change."""
    saved = dict(saved)
    if "music_dir" not in saved and "playlist_dir" in saved:
        saved["music_dir"] = saved.pop("playlist_dir")
    if "unformatted_dir" in saved:
        unformatted = saved.pop("unformatted_dir")
        music_dir = saved.get("music_dir", "")
        if unformatted and unformatted != music_dir:
            saved["use_staging_dir"] = True
            saved["staging_dir"] = unformatted
    toggles = saved.get("toggles", {})
    toggles.pop("wait_for_foobar_replaygain", None)
    saved["toggles"] = toggles
    return saved


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            saved = _migrate(saved)
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
    cfg["music_dir"] = ask_path(
        "Music library folder (where finished songs live)", cfg["music_dir"]
    )

    cfg["use_staging_dir"] = ask_yes_no(
        "\nUse a separate staging folder to look new songs over before "
        "they land in your music folder? (No = tag/fix/ReplayGain/lyrics "
        "everything directly in your music folder, source and destination "
        "the same)",
        cfg["use_staging_dir"],
    )
    if cfg["use_staging_dir"]:
        cfg["staging_dir"] = ask_path(
            "Staging folder", cfg["staging_dir"] or cfg["music_dir"]
        )
    else:
        cfg["staging_dir"] = ""

    t = cfg["toggles"]
    t["fetch_replaygain"] = ask_yes_no(
        "\nAutomatically scan + tag ReplayGain (track and album gain, "
        "matches foobar2000's 'scan as albums (by tags)')?",
        t["fetch_replaygain"],
    )
    t["fetch_lyrics"] = ask_yes_no(
        "Automatically fetch time-synced lyrics (LRCLIB, then NetEase) and "
        "mark instrumentals?",
        t["fetch_lyrics"],
    )
    t["review_lyrics_gaps"] = ask_yes_no(
        "After fetching, walk through tracks that still need a manual "
        "lyric sync (and add genuinely low-lyric songs to the exceptions "
        "list)?",
        t["review_lyrics_gaps"],
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
    setup = ("--setup" in sys.argv) or (not CONFIG_PATH.exists() and not auto)

    cfg = load_config()
    if setup:
        cfg = run_setup(cfg)
    else:
        print(f"Using saved settings from {CONFIG_PATH} (run with --setup to change them).")

    download_dir = cfg["download_dir"]
    music_dir = cfg["music_dir"]
    if not download_dir or not music_dir:
        print("download_dir and music_dir must be set - run with --setup first.")
        sys.exit(1)

    # work_dir is where gathering/converting/tagging/ReplayGain/lyrics all
    # happen. With no staging folder configured this IS music_dir, so every
    # one of those stages runs with source == destination on purpose.
    work_dir = cfg["staging_dir"] if (cfg["use_staging_dir"] and cfg["staging_dir"]) else music_dir
    t = cfg["toggles"]

    for d in (work_dir, music_dir):
        os.makedirs(d, exist_ok=True)

    # ---------------- Stage 1: downloads -> tagged, ReplayGained, lyriced FLACs
    stage("1/4  Gathering new downloads")
    from soulseek_gather_downloads import move_files_to_root
    safe_call(move_files_to_root, download_dir, work_dir)

    stage("2/4  Converting anything that isn't FLAC yet")
    safe_call(convert_downloads_to_flac, work_dir,
               cfg["flac_quality"], cfg["remove_original_after_convert"])

    stage("3/4  Fixing/filling tags and filenames")
    from fix_tags import fix_tags
    safe_call(fix_tags, work_dir)

    if t["fetch_replaygain"]:
        stage("Scanning ReplayGain (track + album, foobar 'scan as albums by tags')")
        fn = try_import("replaygain", "apply_replaygain", "mutagen")
        if fn:
            safe_call(fn, work_dir)

    if t["fetch_lyrics"]:
        stage("Fetching time-synced lyrics (LRCLIB, then NetEase)")
        fn = try_import("lyrics_fetcher", "process_folder", "requests")
        if fn:
            safe_call(fn, work_dir)

    if t["remove_asterisks"]:
        stage("Cleaning censored words out of lyrics")
        fn = try_import("remove_asterixs_from_lyrics", "remove_asterixs_from_lyrics", "colorama")
        if fn:
            safe_call(fn, work_dir)

    if t["translate_lyrics"]:
        stage("Translating non-English lyrics")
        fn = try_import("translate_lyrics", "translate_lyrics", "deep-translator langdetect")
        if fn:
            safe_call(fn, work_dir)

    if t["review_lyrics_gaps"]:
        stage("Reviewing tracks that still need a manual lyric sync")
        fn = try_import("lyrics_checker", "interactive_review", "mutagen")
        if fn:
            safe_call(fn, work_dir)

    stage("4/4  Final review and move into your music folder")
    from final_check import confirm_and_move
    safe_call(confirm_and_move, work_dir, music_dir)

    # ---------------- Stage 2: library-wide polish -----------------------
    if t["normalise_tags"]:
        stage("Normalising inconsistent tags across the library")
        from tag_normaliser import normalise
        safe_call(normalise, music_dir)

    if t["genre_tags"]:
        stage("Fetching genre tags from Last.fm")
        key_file = ensure_lastfm_key()
        subprocess.run([sys.executable, str(SCRIPT_DIR / "genre_tagger.py"),
                         music_dir, "--key-file", key_file], check=False)

    if t["fix_capitalisation"]:
        stage("Fixing capitalisation against Last.fm")
        key_file = ensure_lastfm_key()
        subprocess.run([sys.executable, str(SCRIPT_DIR / "capitalisation_fixer.py"),
                         music_dir, "--key-file", key_file], check=False)

    if t["musicbrainz_ids"]:
        stage("Resolving MusicBrainz artist IDs")
        contact = cfg["contact_email"] or input(
            "Contact email/URL for MusicBrainz User-Agent: "
        ).strip()
        cfg["contact_email"] = contact
        save_config(cfg)
        subprocess.run([sys.executable, str(SCRIPT_DIR / "musicbrainz_id_finder.py"),
                         music_dir, "--contact", contact], check=False)

    stage("Setting cover + artist images (front cover & artist photo only)")
    fn = try_import("image_fixer", "process_library", "Pillow beautifulsoup4 curl_cffi matplotlib")
    if fn:
        safe_call(fn, music_dir)

    if t["downsize"]:
        stage("Downsizing any FLACs above 16-bit/44.1kHz")
        safe_call(downsize_flacs, music_dir, cfg["downsize_in_place"])

    if t["lossless_check"]:
        stage("Scanning for likely transcodes (fake lossless)")
        subprocess.run([sys.executable, str(SCRIPT_DIR / "lossless_checker.py"),
                         music_dir, "--recursive"], check=False)

    print("\n" + "=" * 70)
    print("All done! New songs are formatted, tagged, ReplayGained, lyriced, and in:")
    print(f"  {music_dir}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted - partial progress has already been saved to disk.")
        sys.exit(1)
