#!/usr/bin/env python3
"""
decision_store.py - remember what you already said yes or no to.

The problem this solves: you get asked

    Artist tag:
      Current: King Gizzard & The Lizard Wizard
      New    : King Gizzard; The Lizard Wizard
    Apply this change? (y/n): n

...and then the next King Gizzard track asks you the identical question
again. The stage scripts did cache decisions, but only in a dict that
died with the process, so every run started from nothing.

Decisions now live in ~/.music_pipeline/change_decisions.json and are
reused forever, across runs and across stages.

MATCHING

Two levels, checked in that order:

  1. EXACT - the same old value becoming the same new value. This is the
     default and it's what you almost always want: saying no to
     'King Gizzard & The Lizard Wizard' -> 'King Gizzard; The Lizard Wizard'
     should not leak into an unrelated band.

  2. SIGNATURE - only the spans that actually differ, ignoring the
     unchanged text around them. Used for filenames, where the exact pair
     never repeats (every file has a different name) but the *kind* of
     edit repeats constantly. A rename that turns 'AC,DC' into 'AC-DC'
     has signature (',' -> '-'), so the next file needing the same fix is
     handled without asking. This replaces the old hardcoded
     "AC,DC->AC-DC" special case in fix_tags.py.

Signature matching is opt-in per call (`allow_signature=True`) because
it's deliberately broad.

Decisions are namespaced by `kind` ("artist", "album", "rename", ...) so
an answer about a title never answers a question about a filename.

CLI:
    python3 decision_store.py --list           show everything remembered
    python3 decision_store.py --forget artist  drop one kind
    python3 decision_store.py --clear          drop everything
"""

import json
import os
import tempfile
from pathlib import Path

from change_display import format_change, highlight_pair, is_case_only

DEFAULT_STORE = Path.home() / ".music_pipeline" / "change_decisions.json"

# Kinds where the exact old->new pair essentially never repeats, so the
# differing-spans signature is the useful thing to remember.
SIGNATURE_KINDS = {"rename"}

_SEP = "\u0000"


def _tokens_changed(old, new):
    """The differing spans of old and new, as two joined strings."""
    from change_display import _token_segments  # internal, same package
    a_segs, b_segs = _token_segments(str(old), str(new))
    a = "".join(t for t, changed in a_segs if changed)
    b = "".join(t for t, changed in b_segs if changed)
    return a, b


class DecisionStore:
    """
    A remembered yes/no per (kind, old, new).

    get() returns True (apply), False (skip) or None (never asked).
    """

    def __init__(self, path=None, enabled=True):
        self.path = Path(path) if path else DEFAULT_STORE
        self.enabled = enabled
        self.exact = {}
        self.signature = {}
        self._dirty = False
        if self.enabled:
            self.load()

    # -- persistence -------------------------------------------------------

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self.exact = dict(raw.get("exact", {}))
            self.signature = dict(raw.get("signature", {}))

    def save(self):
        if not self.enabled or not self._dirty:
            return
        payload = {"version": 1, "exact": self.exact, "signature": self.signature}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp file in the same folder, then replace, so an
            # interrupted save can't leave a truncated JSON file behind.
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            pass  # a lost cache is not worth crashing a run over

    # -- lookup ------------------------------------------------------------

    @staticmethod
    def _key(kind, old, new):
        return f"{kind}{_SEP}{old}{_SEP}{new}"

    def get(self, kind, old, new, allow_signature=None):
        if not self.enabled:
            return None
        if allow_signature is None:
            allow_signature = kind in SIGNATURE_KINDS

        key = self._key(kind, old, new)
        if key in self.exact:
            return self.exact[key]

        if allow_signature:
            a, b = _tokens_changed(old, new)
            if a or b:
                sig = self._key(kind, a, b)
                if sig in self.signature:
                    return self.signature[sig]
        return None

    def set(self, kind, old, new, decision, allow_signature=None):
        if not self.enabled:
            return
        if allow_signature is None:
            allow_signature = kind in SIGNATURE_KINDS

        self.exact[self._key(kind, old, new)] = bool(decision)
        if allow_signature:
            a, b = _tokens_changed(old, new)
            if a or b:
                self.signature[self._key(kind, a, b)] = bool(decision)
        self._dirty = True
        self.save()

    def forget(self, kind=None):
        def keep(k):
            return kind is not None and not k.startswith(f"{kind}{_SEP}")
        if kind is None:
            self.exact, self.signature = {}, {}
        else:
            self.exact = {k: v for k, v in self.exact.items() if keep(k)}
            self.signature = {k: v for k, v in self.signature.items() if keep(k)}
        self._dirty = True
        self.save()

    def entries(self):
        """Yield (kind, old, new, decision, matching) for display."""
        for store, matching in ((self.exact, "exact"), (self.signature, "signature")):
            for key, decision in sorted(store.items()):
                parts = key.split(_SEP)
                if len(parts) == 3:
                    yield parts[0], parts[1], parts[2], decision, matching

    # -- the thing the stage scripts actually call -------------------------

    def confirm_change(self, kind, old, new, ask, label=None,
                       allow_signature=None, auto_case=True):
        """
        Show a change, then return True/False for whether to apply it.

        Order of decision:
          1. capitalisation-only  -> yes, silently (never asked, never stored)
          2. already remembered   -> reuse it, say so
          3. otherwise            -> call `ask` and remember the answer

        `ask` is a callable taking a prompt string and returning a bool.
        """
        old, new = str(old), str(new)
        heading = label or f"{kind.capitalize()} change"
        print(f"{heading}:")
        print(format_change(old, new, old_label="Current", new_label="New"))

        if auto_case and is_case_only(old, new):
            from change_display import auto_applied_note
            print(auto_applied_note("change"))
            return True

        remembered = self.get(kind, old, new, allow_signature=allow_signature)
        if remembered is not None:
            verdict = "applying" if remembered else "skipping"
            print(f"  (remembered your earlier answer - {verdict}; "
                  f"run 'python3 decision_store.py --forget {kind}' to be asked again)")
            return remembered

        answer = bool(ask("Apply this change?"))
        self.set(kind, old, new, answer, allow_signature=allow_signature)
        return answer


def _main():
    import argparse
    p = argparse.ArgumentParser(description="Inspect or clear remembered change decisions.")
    p.add_argument("--store", default=None, help=f"Path to the store (default: {DEFAULT_STORE})")
    p.add_argument("--list", action="store_true", help="List every remembered decision")
    p.add_argument("--forget", metavar="KIND", help="Forget all decisions of one kind (e.g. artist)")
    p.add_argument("--clear", action="store_true", help="Forget everything")
    args = p.parse_args()

    store = DecisionStore(args.store)

    if args.clear:
        store.forget()
        print("Cleared all remembered decisions.")
        return
    if args.forget:
        store.forget(args.forget)
        print(f"Forgot all '{args.forget}' decisions.")
        return

    rows = list(store.entries())
    if not rows:
        print(f"Nothing remembered yet ({store.path}).")
        return
    print(f"{len(rows)} remembered decision(s) in {store.path}:\n")
    for kind, old, new, decision, matching in rows:
        mark = "APPLY " if decision else "SKIP  "
        note = "" if matching == "exact" else "   [pattern]"
        old_h, new_h = highlight_pair(old, new)
        print(f"  {mark} [{kind}]{note}")
        print(f"      {old_h}")
        print(f"   -> {new_h}")
    print(f"\nUse --forget KIND or --clear to be asked about these again.")


if __name__ == "__main__":
    _main()
