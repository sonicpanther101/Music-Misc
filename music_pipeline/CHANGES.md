# What changed

## 1. Two folders instead of three, and same-folder mode actually works

`run.py`'s config used to require three paths: `download_dir`,
`unformatted_dir` (staging), `playlist_dir`. Now it's just:

- `download_dir` - where new songs land
- `music_dir` - your library

By default the fix-tags/ReplayGain/lyrics stages run **directly on
`music_dir`** - source and destination are the same folder, same as
pointing TagScanner at your library. `final_check.py` used to compute a
`same_dir` flag and then never use it (a leftover bug); it now actually
skips the "already exists at destination" check and the file move when
source and destination are the same, and just asks you to confirm the file
is in good shape.

If you want a separate holding folder to look things over before they mix
into your library, turn on "use a staging folder" during setup and a third
folder is used exactly like the old `unformatted_dir` did, with a real move
into `music_dir` at the end.

Old config files (`~/.music_pipeline/config.json`) are migrated
automatically the first time you run this version - nothing is lost.

## 2. ReplayGain and lyrics are no longer a "go do this in Foobar" step

`run.py` used to stop and tell you to go set ReplayGain and lyrics in
Foobar2000 by hand. `replaygain.py` and `lyrics_fetcher.py` already existed
and already did the right thing (foobar-style "scan as albums by tags" for
ReplayGain; LRCLIB then NetEase for lyrics, instrumental detection, plain
lyrics kept as a sync stopgap) - they just weren't wired into the main run.
Now they run automatically as part of the pipeline, and
`lyrics_checker.interactive_review()` runs right after so you can either
sync-by-ear the genuine gaps or mark a track as a confirmed few-lyrics
exception on the spot.

Order matters here: ReplayGain and lyrics now run *after* `fix_tags`
(needs correct ARTIST/TITLE/ALBUM to search/group by) and *before* the
final move.

## 3. TUI

`tui.py` (needs `pip install textual --break-system-packages`) gives you:

- **Setup** - the same folders/toggles as `run.py --setup`, as a form.
- **Run pipeline** - runs `run.py --auto` as a subprocess, streams its
  output into a scrollback log, and forwards anything you type into an
  input box straight to that subprocess's stdin. Every existing prompt
  (missing tag, rename this file?, add to exceptions?) shows up here
  unchanged - none of the underlying stage scripts needed to be rewritten
  to make this work.
- **Lyrics exceptions** - a table view over the same
  `~/.music_pipeline/lyrics_exceptions.json` `ExceptionsStore`, so you can
  add or remove "this one genuinely only has a few lines" entries without
  going through the CLI review loop at all.

Run it with `python3 tui.py`.

## 4. Capitalisation-only changes are never a question

Previously, `fix_tags.py` compared the current and expected filename with
a plain `!=`, so this was a prompt:

    Filename differs:
      Current:  All of My Stars - Daniel Champagne - Fault Lines.flac
      Expected: All Of My Stars - Daniel Champagne - Fault Lines.flac
    Rename file? (y/n):

Nothing is being decided there. Across the pipeline, if the *only*
difference between the old and new value is capitalisation, the change is
now applied automatically and printed, never asked about.

New shared module **`change_display.py`** holds the single definition of
"only capitalisation changed" (`is_case_only`, using `casefold()` so
`STRASSE`/`straße` counts too) plus the highlighting described below, so
every stage agrees rather than each having its own idea.

What changed where:

- **`fix_tags.py`** - case-only renames happen silently. Renames now go
  through `rename_preserving_case()`, which routes a case-only rename via
  a temporary filename: on a case-insensitive filesystem (Windows, macOS
  by default) the source and destination are literally the same file, so
  a direct `os.rename` is either a no-op or an error. Every tag prompt
  (date, artist, title, album, remaster) goes through `confirm_change()`,
  which auto-applies case-only edits.
- **`capitalisation_fixer.py`** - already skipped pure-case prompts for a
  single match, but when Last.fm returned *several* entries it asked you
  to pick between them. Those entries were already filtered to
  case-insensitive matches of your tag, so every option differed by
  capitalisation and nothing else. It now takes the most-listened
  spelling automatically. You are still asked when Last.fm found nothing
  at all, since that needs a spelling or a URL from you.
- **`tag_normaliser.py`** - `are_likely_duplicates()` deliberately groups
  values that match when lowercased, and then handed the group to a
  "Select option (1-N)" prompt. Groups where every variant is the same
  text in different case are now resolved automatically: majority
  spelling wins, ties break against ALL CAPS and all lowercase (so
  `Brand New Eyes` beats `BRAND NEW EYES` and `brand new eyes`). Mixed
  groups still prompt.
- **`remove_asterixs_from_lyrics.py`**, **`translate_lyrics.py`** - same
  rule applied to lyric line edits.

## 5. Changes are highlighted, so you can see what's actually changing

Every before/after in the pipeline now diffs the two values and colours
only the part that differs, with the surrounding text dimmed:

- a pure-capitalisation change marks the individual letters whose case
  flipped, in yellow, on both lines;
- a substantive change marks the removed span in red and the added span
  in green, diffed on word boundaries rather than per character so a
  changed word reads as one block;
- labels are padded so both values start in the same column, which is
  what makes a one-letter difference pop.

With colour off, changed spans are bracketed instead - `All [o]f My
Stars` - so the highlighting survives being pasted into a bug report or
a log file.

Colour is controlled by, in priority order:

    MUSIC_PIPELINE_NO_COLOR=1     never colour (NO_COLOR also honoured)
    MUSIC_PIPELINE_FORCE_COLOR=1  always colour, even when piped
    otherwise                     colour only when stdout is a terminal

## 6. The TUI log is selectable text

The run log was a `RichLog`, which you can't select with the mouse - so
getting a filename or a traceback out of it meant OCR'ing a screenshot.
It was also swallowing the pipeline's colour, because `RichLog.write()`
doesn't interpret ANSI escapes.

Both fixed:

- Log lines are rendered through `rich.text.Text.from_ansi()`, so the new
  highlighting shows up as actual colour instead of `\x1b[1;33m` noise.
  `tui.py` sets `MUSIC_PIPELINE_FORCE_COLOR=1` for the subprocess, since
  its stdout is a pipe and it would otherwise switch colour off.
- A plain-text copy of every line is kept alongside, with the escape
  codes stripped. That backs three new ways of getting text out:

      ctrl+t   freeze the log into a selectable read-only text view, and
               back to the live log again
      ctrl+y   copy the whole log to the clipboard
      ctrl+s   save the whole log to pipeline-log-<timestamp>.txt

  ...also available as buttons next to Stop.

The ctrl+t view is deliberately a *snapshot*: if it kept appending while
you were dragging a selection, the selection would jump around under the
cursor. Press ctrl+t again to return to the live log.

`App.ALLOW_SELECT` is also set, so on Textual 3.0+ plain mouse-drag
selection works anywhere without toggling at all. Older versions ignore
the attribute and the ctrl+t view covers them.

## 7. Your yes/no answers are remembered, permanently

Saying `n` to

    Artist tag:
      Current: King Gizzard & The Lizard Wizard
      New    : King Gizzard; The Lizard Wizard

...and then being asked the identical question on the next King Gizzard
track was the result of decisions living in dicts that died with the
process (`artist_preferences`, `rename_preferences` in `fix_tags.py`).

New module **`decision_store.py`** persists them to
`~/.music_pipeline/change_decisions.json`, reused across runs and across
stages. Decisions are namespaced by kind ("artist", "album", "rename",
"remaster", "normalise:<tag>") so an answer about a title can never
answer a question about a filename.

Matching happens at two levels:

- **Exact** - the same old value becoming the same new value. This is the
  default, and it's what you want for tags: refusing
  `King Gizzard & The Lizard Wizard` -> `King Gizzard; The Lizard Wizard`
  must not leak into `Simon & Garfunkel`, which is still asked about
  separately.
- **Signature** - only the spans that actually differ, ignoring the
  unchanged text around them. Used for filenames, where the exact pair
  never repeats (every file has a different name) but the kind of edit
  repeats constantly. A rename turning `AC,DC` into `AC-DC` is stored as
  `,` -> `-`, so the next file needing that fix is handled silently.

That signature matching **replaces the hardcoded `AC,DC->AC-DC` special
case** that used to be the only rename pattern `fix_tags.py` understood.
Every recurring rename now generalises, not just that one band.

Reviewing and undoing decisions:

    python3 decision_store.py --list           show everything remembered
    python3 decision_store.py --forget artist  drop one kind
    python3 decision_store.py --clear          drop everything

...or the new **"Saved yes/no decisions"** screen in the TUI, which lists
them in a table and lets you remove individual entries.

When a remembered answer is used, the pipeline says so rather than
silently skipping, so a wrong answer is visible instead of mysterious:

    (remembered your earlier answer - skipping; run
     'python3 decision_store.py --forget artist' to be asked again)

Writes are atomic (temp file plus `os.replace`), so a Ctrl+C mid-save
can't leave a truncated JSON file that breaks the next run.

## 8. TUI: prompts are visible *before* you answer them

A real bug, visible in the log above: the question appeared after the
answer.

    Artist tag:
      Current: King Gizzard & The Lizard Wizard
      New    : King Gizzard; The Lizard Wizard
    > n
    Apply this change? (y/n): ✔ No tag changes needed for: ...

`RunScreen` read the subprocess with `readline()`, which waits for a
newline. But a prompt like `Apply this change? (y/n): ` deliberately has
no trailing newline - it ends with a space so you type on the same line.
So the prompt sat in the buffer, unread, until something else printed
after it. You were answering questions you couldn't see.

The read loop now pulls raw chunks instead, emits complete lines
immediately, and flushes whatever partial line is left over once the
pipeline goes quiet for ~150ms - which is exactly when it's sitting
there waiting for you. Questions now appear when they're asked.

## 9. Lyrics-fetch crash: NetEase returning a bare string instead of JSON

    error ('str' object has no attribute 'get')
    Lyrics fetch summary:
      ...
      error: 14

NetEase's unofficial API sometimes answers a blocked or rate-limited
request with a bare JSON string (e.g. `"-460"`) instead of the
`{"result": {"songs": [...]}}` shape the code expected. `r.json()`
parses that fine - it's valid JSON - so no exception was raised there;
the crash came one line later, calling `.get()` on what turned out to be
a `str`. Every file whose NetEase lookup got one of these responses
counted as a hard "error" for the whole file, even when LRCLIB might
already have answered, or NetEase's answer for that specific file just
happened to be malformed while the file itself was perfectly fine.

Fixed in `lyrics_fetcher.py`:

- `netease_search()`, `netease_lyric()`, and the LRCLIB equivalents now
  check `isinstance(..., dict)` (or `list`, for LRCLIB's search
  endpoint) at every step before calling `.get()` on anything a server
  sent back. An unexpected shape is now treated as "no results", not a
  crash.
- LRCLIB and NetEase are now tried independently: an exception in one no
  longer skips the other. Only if *neither* produces anything does the
  file get reported as an error, and the message says which source(s)
  failed and why (`"LRCLIB: <reason>; NetEase: <reason>"`) instead of a
  bare, out-of-context Python exception.

## 10. Translate: no more debug spam, and translated songs stay translated

Two things here: `translate_lyrics.py` had a debug print literally
labelled `# <-- temporary debug line` that was never removed, and there
was no durable way to tell "this song has already been through
translation" from "this song has never been looked at" - so a song
stayed flagged, and got re-shown the same debug output, on every single
run, forever.

- **Debug spam gone.** The `[non-ascii after normalize]` / `[flagged]`
  prints only show now with `MUSIC_PIPELINE_DEBUG_TRANSLATE=1` set -
  still available for troubleshooting, off by default.

- **"Already translated" is now a real, permanent fact about the file,
  not a guess re-computed every run.** Two new tags:

      lyrics_translated             "1" once a translation was applied
      lyrics_translate_declined_hash   hash of the text you said [n]o to

  These live *on the FLAC file itself* rather than in an external cache
  keyed by path, deliberately - `fix_tags.py` renames and moves these
  files constantly, and a path-keyed cache would silently stop matching
  the moment a file's name gets corrected. Tags travel with the file.

  Checked in order, before any of the (printy) "does this need
  translating" analysis even runs:
    1. `lyrics_translated == "1"` -> skip immediately, silently.
    2. the declined-hash matches the *current* lyrics text -> skip, and
       say so. If the lyrics later change (a better sync comes in, you
       hand-edit them), the hash won't match and you're asked again -
       about the new text, which is correct, not a bug to route around.
    3. the existing ratio-based `already_translated()` heuristic is kept
       as a second check (catches translations applied by an older copy
       of this script, before these tags existed) - and now *backfills*
       `lyrics_translated` when it fires, so that's a one-time cost per
       file rather than a heuristic re-run forever.

- **Recursive folder walk.** `translate_lyrics()` used `os.listdir()`,
  not `os.walk()`/`rglob()` like every other stage - a library organised
  as Artist/Album subfolders was silently never processed by this stage
  at all if pointed at the library root. Now walks recursively, matching
  `lyrics_fetcher.py` and `lyrics_checker.py`.

- **`input()` calls fail safe.** None of this script's prompts handled
  `EOFError` - in a genuinely unattended context (stdin already closed)
  the very first prompt would crash the script outright, mid-library,
  with no per-file cleanup. All prompts now go through a small `ask()`
  helper that treats EOF as "no"/"quit" instead of crashing.

- **A write-time safety net.** A translation pass only ever *appends*
  lines - the original line is always kept, with a translated line added
  after it - so the result can never legitimately end up shorter than
  what you started with. If it somehow did, the file is now left alone
  and a `[SAFETY]` message is printed, rather than saving something with
  less content than it had before. This won't silently mask a bug, but
  it does turn "lyrics quietly vanished, discovered days later" into
  "the pipeline told you exactly which file it refused to touch, and
  why" - a state you can find and act on immediately, whatever bug (in
  this codebase or otherwise) actually causes it in a given run.
