"""
exceptions_store.py - shared, editable "few lyrics" exceptions list.

lyrics_checker.py flags any FLAC whose lyrics tag has fewer than 5 lines
that look like [mm:ss.xx] timestamps, on the theory that a real song has
more sync points than that. Some songs are legitimately short on lyrics
(a one-line hook repeated, a mostly-instrumental track with a few spoken
words, etc.) - those go on this exceptions list so the checker stops
nagging about them.

Previously this lived as a hardcoded `songExclusions` list at the top of
lyrics_checker.py. It's now a small JSON file so both the TUI and the
plain script can add/remove entries without editing source.
"""

import json
from pathlib import Path

DEFAULT_PATH = Path.home() / ".music_pipeline" / "lyrics_exceptions.json"

# Seeded with the entries that used to be hardcoded, so nothing is lost
# the first time this runs.
_SEED = [
    {"artist": "Blink-182", "title": "The Fallen Interlude"},
    {"artist": "Blink-182", "title": "Fuck Face"},
    {"artist": "Car Seat Headrest", "title": "Stop Smoking"},
    {"artist": "DIIV", "title": "Home"},
    {"artist": "Daft Punk", "title": "Superheroes"},
]


def _normalise(s):
    return (s or "").strip().casefold()


class ExceptionsStore:
    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else DEFAULT_PATH
        self.entries = self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError):
                print(f"Warning: couldn't read {self.path}, starting fresh.")
        return list(_SEED)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, ensure_ascii=False)

    def contains(self, artist, title):
        a, t = _normalise(artist), _normalise(title)
        for e in self.entries:
            ea, et = _normalise(e.get("artist", "")), _normalise(e.get("title", ""))
            # substring match on both sides, same behaviour lyrics_checker
            # used to have with its "any(s in ...)" check
            if ea and et and (ea in a or a in ea) and (et in t or t in et):
                return True
        return False

    def add(self, artist, title, reason=""):
        if self.contains(artist, title):
            return False
        self.entries.append({"artist": artist, "title": title, "reason": reason})
        self.save()
        return True

    def remove(self, artist, title):
        before = len(self.entries)
        a, t = _normalise(artist), _normalise(title)
        self.entries = [
            e for e in self.entries
            if not (_normalise(e.get("artist", "")) == a and _normalise(e.get("title", "")) == t)
        ]
        changed = len(self.entries) != before
        if changed:
            self.save()
        return changed


if __name__ == "__main__":
    store = ExceptionsStore()
    print(f"{len(store.entries)} exception(s) in {store.path}")
    for e in store.entries:
        print(f"  {e['artist']} - {e['title']}" + (f"  ({e['reason']})" if e.get("reason") else ""))
