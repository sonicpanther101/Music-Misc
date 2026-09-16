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
