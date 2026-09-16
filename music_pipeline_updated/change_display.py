#!/usr/bin/env python3
"""
change_display.py - one place for "what is actually changing here?"

Two jobs, shared by every stage script:

1. CASE-ONLY CHANGES ARE NEVER WORTH ASKING ABOUT.
   `is_case_only()` and `all_case_only()` answer "do these differ by
   nothing but capitalisation?". Stage scripts use that to apply the
   change silently instead of putting a y/n prompt in your way. The
   change is still *printed*, just not *asked* about.

2. HIGHLIGHT THE DIFFERENCE.
   `format_change()` / `format_inline()` diff the old and new value and
   colour only the characters that actually differ, so a one-letter
   change in a long album name is obvious at a glance instead of
   something you have to spot by reading both lines character by
   character.

Colour control (in priority order):
    MUSIC_PIPELINE_NO_COLOR=1    -> never colour (also honours NO_COLOR)
    MUSIC_PIPELINE_FORCE_COLOR=1 -> always colour, even when piped
    otherwise                    -> colour only when stdout is a terminal

The TUI sets MUSIC_PIPELINE_FORCE_COLOR=1 for the pipeline subprocess,
because its output is a pipe but it *does* render colour.

With colour off, changed spans are bracketed instead - [like this] - so
the highlighting still survives in a log file or a screenshot-free copy
and paste.
"""

import difflib
import os
import re
import sys

__all__ = [
    "is_case_only", "all_case_only", "case_insensitive_key",
    "highlight_pair", "format_change", "format_inline",
    "pick_case_variant", "auto_applied_note", "colour_enabled",
]

# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

_RESET = "\033[0m"
_OLD = "\033[1;31m"      # bold red   - the part being replaced
_NEW = "\033[1;32m"      # bold green - the part replacing it
_DIM = "\033[2m"         # dim        - the unchanged surroundings
_CASE = "\033[1;33m"     # bold yellow - a pure-capitalisation change
_LABEL = "\033[1m"


def colour_enabled() -> bool:
    if os.environ.get("MUSIC_PIPELINE_NO_COLOR") or os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("MUSIC_PIPELINE_FORCE_COLOR"):
        return True
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _wrap(text: str, colour: str) -> str:
    if not text:
        return ""
    if colour_enabled():
        return f"{colour}{text}{_RESET}"
    return f"[{text}]"


def _plain(text: str) -> str:
    if not text:
        return ""
    return f"{_DIM}{text}{_RESET}" if colour_enabled() else text


def _bold(text: str) -> str:
    return f"{_LABEL}{text}{_RESET}" if colour_enabled() else text


# --------------------------------------------------------------------------
# Case-only detection
# --------------------------------------------------------------------------

def is_case_only(old, new) -> bool:
    """
    True when `old` and `new` are different strings that are identical
    once case is ignored - i.e. the only thing changing is capitalisation.

    Uses casefold(), not lower(), so this is also true for things like
    'STRASSE' vs 'straße' where lower() alone would disagree.
    """
    if old is None or new is None:
        return False
    old, new = str(old), str(new)
    return old != new and old.casefold() == new.casefold()


def all_case_only(values) -> bool:
    """
    True when every value in `values` is the same string ignoring case,
    but they are not all literally identical. Use this for "a group of
    variant spellings that turned out to be just capitalisation".
    """
    values = [str(v) for v in values if v is not None]
    if len(values) < 2:
        return False
    folded = {v.casefold() for v in values}
    return len(folded) == 1 and len(set(values)) > 1


def case_insensitive_key(value) -> str:
    return "" if value is None else str(value).casefold()


# --------------------------------------------------------------------------
# Highlighting
# --------------------------------------------------------------------------

# Split into words, whitespace and single punctuation marks, so the diff
# lands on meaningful chunks instead of scattering across every letter.
_TOKEN_RE = re.compile(r"\w+|\s+|\W", re.UNICODE)


def _tokens(text: str):
    return _TOKEN_RE.findall(text)


def _render(segments, colour):
    """
    Turn [(text, changed?), ...] into a display string, merging adjacent
    runs of the same state first so a five-letter change is one escape
    sequence (or one pair of brackets), not five.
    """
    merged = []
    for text, changed in segments:
        if not text:
            continue
        if merged and merged[-1][1] == changed:
            merged[-1][0] += text
        else:
            merged.append([text, changed])
    return "".join(_wrap(t, colour) if c else _plain(t) for t, c in merged)


def _case_segments(old: str, new: str):
    """Character-aligned changed/unchanged segments for a pure-case change."""
    a_segs, b_segs = [], []
    for a, b in zip(old, new):
        changed = a != b
        a_segs.append((a, changed))
        b_segs.append((b, changed))
    return a_segs, b_segs


def _token_segments(old: str, new: str):
    a_tok, b_tok = _tokens(old), _tokens(new)
    matcher = difflib.SequenceMatcher(a=a_tok, b=b_tok, autojunk=False)
    a_segs, b_segs = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        changed = tag != "equal"
        a_segs.append(("".join(a_tok[i1:i2]), changed))
        b_segs.append(("".join(b_tok[j1:j2]), changed))
    return a_segs, b_segs


def highlight_pair(old, new):
    """
    Return (old_highlighted, new_highlighted): the same two strings, with
    only the differing spans marked up. Unchanged text is dimmed so the
    changed part is what your eye lands on.

    For a pure-capitalisation change both sides are marked in yellow, and
    the marked spans are the specific letters whose case flipped.
    """
    old = "" if old is None else str(old)
    new = "" if new is None else str(new)

    if old == new:
        return _plain(old), _plain(new)

    case_change = is_case_only(old, new)
    old_colour = _CASE if case_change else _OLD
    new_colour = _CASE if case_change else _NEW

    # For a genuine case-only change of equal length, a character walk is
    # exact and far more precise than a token diff. casefold() can change
    # length (e.g. 'ß' -> 'ss'), so fall back to tokens when it does.
    if case_change and len(old) == len(new):
        a_segs, b_segs = _case_segments(old, new)
    else:
        a_segs, b_segs = _token_segments(old, new)

    return _render(a_segs, old_colour), _render(b_segs, new_colour)


def format_change(old, new, old_label="Current", new_label="Expected",
                  indent="  ", quote=False):
    """
    A two-line block showing the change with the difference highlighted:

        Current:  All of My Stars - Daniel Champagne - Fault Lines.flac
        Expected: All Of My Stars - Daniel Champagne - Fault Lines.flac

    ...where only the flipped letter is coloured on each line. Labels are
    padded so the two values start in the same column, which is what makes
    a small difference visually pop.
    """
    old_h, new_h = highlight_pair(old, new)
    if quote:
        old_h, new_h = f"'{old_h}'", f"'{new_h}'"
    width = max(len(old_label), len(new_label))
    return (f"{indent}{_bold(old_label.ljust(width))}: {old_h}\n"
            f"{indent}{_bold(new_label.ljust(width))}: {new_h}")


def format_inline(old, new, quote=True):
    """
    A one-line 'old' -> 'new' with the difference highlighted. Use where a
    change is mentioned mid-sentence rather than shown as a block.
    """
    old_h, new_h = highlight_pair(old, new)
    if quote:
        return f"'{old_h}' \u2192 '{new_h}'"
    return f"{old_h} \u2192 {new_h}"


def auto_applied_note(what="change", indent="  "):
    """The standard 'I didn't ask because it's only capitalisation' line."""
    body = f"capitalisation only - applying this {what} automatically"
    return f"{indent}{_wrap(body, _CASE) if colour_enabled() else body}"


# --------------------------------------------------------------------------
# Choosing between capitalisation variants without asking
# --------------------------------------------------------------------------

def _variant_score(value: str, count: int):
    """
    Rank one spelling of a value against its case-variant siblings.

    Preference order, most important first:
      1. the spelling used by the most files (majority wins)
      2. not ALL CAPS and not all lowercase (those are almost always the
         sloppy ones; 'Brand New Eyes' beats 'BRAND NEW EYES')
      3. more capitalised words (title case beats sentence case)
      4. alphabetical, purely so the result is deterministic
    """
    letters = [c for c in value if c.isalpha()]
    all_upper = bool(letters) and all(c.isupper() for c in letters)
    all_lower = bool(letters) and all(c.islower() for c in letters)
    shouty_or_lazy = all_upper or all_lower
    capitalised_words = sum(1 for w in value.split() if w[:1].isupper())
    return (count, 0 if shouty_or_lazy else 1, capitalised_words, value)


def pick_case_variant(counts: dict):
    """
    Given {spelling: number_of_files}, pick the spelling to standardise on.
    Only meaningful when every key is the same string ignoring case.
    """
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: _variant_score(kv[0], kv[1]))[0]


if __name__ == "__main__":
    # Quick visual self-test:  python3 change_display.py
    os.environ.setdefault("MUSIC_PIPELINE_FORCE_COLOR", "1")
    samples = [
        ("All of My Stars - Daniel Champagne - Fault Lines.flac",
         "All Of My Stars - Daniel Champagne - Fault Lines.flac"),
        ("Brand New Eyes", "brand new eyes"),
        ("Sigur Ros", "Sigur R\u00f3s"),
        ("The Dark Side of the Moon", "The Dark Side of the Moon (2011 Remaster)"),
        ("AC,DC", "AC-DC"),
    ]
    for a, b in samples:
        print(format_change(a, b))
        print(f"  case-only: {is_case_only(a, b)}")
        print(f"  inline:    {format_inline(a, b)}\n")
