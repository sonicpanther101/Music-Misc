"""
lyrics_checker.py - find tracks that still need a human to sync lyrics.

Run this *after* lyrics_fetcher.py, once LRCLIB/NetEase have already had a
go at everything. What's left here is the genuinely manual pile: nothing
found anywhere, or a track has so few timestamp lines that it's probably
missing its lyrics tag entirely rather than genuinely being lyric-sparse.

Anything on the exceptions list (exceptions_store.py) - songs you've
already checked and confirmed really do only have a couple of lines - is
skipped.
"""

import os

from mutagen.flac import FLAC

from exceptions_store import ExceptionsStore

MIN_TIMESTAMPS = 5


def _get(audio, tag, default=""):
    return audio[tag][0] if tag in audio and audio[tag] else default


def check_time_sync(folder_path, exceptions=None):
    """Walk `folder_path` for FLACs needing manual lyric attention.

    Returns a list of dicts: {path, artist, title, album, timestamps,
    reason} where reason is "unsynced_or_missing" (few/no timestamp
    lines) or "unresolved_marker" (a lyric line literally contains
    "[?]", meaning a previous manual-sync pass was left half-done).
    """
    exceptions = exceptions or ExceptionsStore()
    issues = []

    for root, _, files in os.walk(folder_path):
        for name in files:
            if not name.lower().endswith(".flac"):
                continue
            file_path = os.path.join(root, name)
            try:
                audio = FLAC(file_path)
            except Exception as e:
                print(f"[skip - couldn't read {name}: {e}]")
                continue

            artist = _get(audio, "artist")
            title = _get(audio, "title")
            album = _get(audio, "album")

            if audio.get("instrumental", [""])[0] == "1":
                continue
            if exceptions.contains(artist, title):
                continue

            lyrics = _get(audio, "lyrics")
            if not lyrics:
                issues.append({
                    "path": file_path, "artist": artist, "title": title,
                    "album": album, "timestamps": 0, "reason": "unsynced_or_missing",
                })
                continue

            lines = lyrics.split("\n")
            timestamps = 0
            unresolved = False
            for line in lines:
                if "[?]" in line:
                    unresolved = True
                if "[" in line and ":" in line:
                    timestamps += 1
                if "纯音乐，请欣赏" in line:
                    timestamps = -100  # instrumental marker slipped through untagged

            if unresolved:
                issues.append({
                    "path": file_path, "artist": artist, "title": title,
                    "album": album, "timestamps": timestamps, "reason": "unresolved_marker",
                })
            elif timestamps < MIN_TIMESTAMPS:
                issues.append({
                    "path": file_path, "artist": artist, "title": title,
                    "album": album, "timestamps": timestamps, "reason": "unsynced_or_missing",
                })

    return issues


def print_issues(issues):
    if not issues:
        print("Nothing needs manual attention - everything is synced (or excepted).")
        return
    print(f"{len(issues)} track(s) need manual attention:\n")
    print(f"{'Artist':30} {'Title':30} {'Album':30} {'Lines':>6}  Reason")
    for i in issues:
        print(f"{i['artist'][:30]:30} {i['title'][:30]:30} {i['album'][:30]:30} "
              f"{i['timestamps']:>6}  {i['reason']}")


def interactive_review(folder_path):
    """CLI walkthrough: for each flagged track, decide to add it as an
    exception (few lyrics, it's fine) or leave it for manual syncing."""
    store = ExceptionsStore()
    issues = check_time_sync(folder_path, store)
    if not issues:
        print_issues(issues)
        return

    print(f"{len(issues)} track(s) need manual attention.\n")
    for i in issues:
        print(f"\n{i['artist']} - {i['title']} ({i['album']})  [{i['reason']}, "
              f"{i['timestamps']} timestamp line(s)]")
        ans = input("  (s)kip / (e)xception - few lyrics is correct / (q)uit: ").strip().lower()
        if ans == "e":
            store.add(i["artist"], i["title"], reason="confirmed few/no lyrics")
            print("  Added to exceptions.")
        elif ans == "q":
            break


if __name__ == "__main__":
    import sys
    folder_path = sys.argv[1] if len(sys.argv) > 1 else "."
    if "--review" in sys.argv:
        interactive_review(folder_path)
    else:
        print_issues(check_time_sync(folder_path))
