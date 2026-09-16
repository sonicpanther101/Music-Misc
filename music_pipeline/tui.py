#!/usr/bin/env python3
"""
tui.py - a Textual front end for the music pipeline.

Three screens:
  1. Setup       - the same folders/toggles run.py --setup asks for, as a
                    proper form instead of a stream of y/n prompts.
  2. Run         - launches `run.py --auto` as a subprocess and shows its
                    output in a scrolling log, with an input box wired to
                    that subprocess's stdin. Every interactive question the
                    stages already ask (a missing tag, "rename this file?",
                    "add to exceptions?") shows up right here - nothing
                    about the underlying scripts had to change for this.

                    The log is colour (the pipeline's highlighted diffs
                    come through as colour, not as raw escape codes) AND
                    it can be selected and copied as text:

                      ctrl+t  freeze the log into a selectable text view
                              and back again
                      ctrl+y  copy the whole log to the clipboard
                      ctrl+s  save the whole log to a .txt file

                    So you never have to OCR a screenshot to get a
                    stack trace or a filename out of it.
  3. Exceptions  - browse/add/remove the "few lyrics is fine" list directly,
                    as an alternative to the CLI review loop.

Install:  pip install textual --break-system-packages
Run:      python3 tui.py
"""

import asyncio
import datetime as _dt
import os
import re
import sys
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button, Checkbox, DataTable, Footer, Header, Input, Label, RichLog, Static,
    TextArea, ProgressBar,
)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Strips the colour codes back out again for the plain-text copy of the log.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

import run as pipeline  # noqa: E402  (reuse load_config/save_config/DEFAULT_CONFIG)
from exceptions_store import ExceptionsStore  # noqa: E402
from decision_store import DecisionStore  # noqa: E402


# --------------------------------------------------------------------------
# Setup screen
# --------------------------------------------------------------------------

class SetupScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self):
        super().__init__()
        self.cfg = pipeline.load_config()

    def compose(self) -> ComposeResult:
        c = self.cfg
        t = c["toggles"]
        yield Header(show_clock=False)
        with VerticalScroll(id="setup-body"):
            yield Static("[b]Folders[/b]")
            yield Label("Downloads folder (e.g. Soulseek 'complete' folder)")
            yield Input(value=c["download_dir"], id="download_dir", placeholder="/path/to/downloads")
            yield Label("Music library folder")
            yield Input(value=c["music_dir"], id="music_dir", placeholder="/path/to/music")
            yield Checkbox("Use a separate staging folder before songs hit the library",
                            value=c["use_staging_dir"], id="use_staging_dir")
            yield Label("Staging folder (only used if the box above is checked)")
            yield Input(value=c["staging_dir"], id="staging_dir", placeholder="/path/to/staging")

            yield Static("\n[b]Automated fill-in (replaces Foobar/TagScanner)[/b]")
            yield Checkbox("Scan + tag ReplayGain (track + album, foobar 'scan as albums by tags')",
                            value=t["fetch_replaygain"], id="fetch_replaygain")
            yield Checkbox("Fetch time-synced lyrics (LRCLIB then NetEase), mark instrumentals",
                            value=t["fetch_lyrics"], id="fetch_lyrics")
            yield Checkbox("Review leftover lyric gaps interactively (exceptions list)",
                            value=t["review_lyrics_gaps"], id="review_lyrics_gaps")
            yield Checkbox("Scan lyrics for censored (****) words",
                            value=t["remove_asterisks"], id="remove_asterisks")
            yield Checkbox("Offer to translate non-English lyric lines",
                            value=t["translate_lyrics"], id="translate_lyrics")

            yield Static("\n[b]Library-wide polish[/b]")
            yield Checkbox("Normalise inconsistent tag spellings",
                            value=t["normalise_tags"], id="normalise_tags")
            yield Checkbox("Fetch GENRE tags from Last.fm",
                            value=t["genre_tags"], id="genre_tags")
            yield Checkbox("Fix title/artist/album capitalisation against Last.fm",
                            value=t["fix_capitalisation"], id="fix_capitalisation")
            yield Checkbox("Resolve MusicBrainz artist IDs",
                            value=t["musicbrainz_ids"], id="musicbrainz_ids")
            yield Label("Contact email/URL for MusicBrainz (only needed if the box above is checked)")
            yield Input(value=c["contact_email"], id="contact_email", placeholder="you@example.com")
            yield Checkbox("Downsize FLACs above 16-bit/44.1kHz",
                            value=t["downsize"], id="downsize")
            yield Checkbox("  ...replace the original in place (vs. keep both)",
                            value=c["downsize_in_place"], id="downsize_in_place")
            yield Checkbox("Run the transcode/fake-lossless detector at the end",
                            value=t["lossless_check"], id="lossless_check")

            yield Static("\n[b]Conversion[/b]")
            yield Label("FLAC compression level (0-12)")
            yield Input(value=str(c["flac_quality"]), id="flac_quality")
            yield Checkbox("Delete original file after converting to FLAC",
                            value=c["remove_original_after_convert"], id="remove_original_after_convert")

            with Horizontal(id="setup-buttons"):
                yield Button("Save", id="save", variant="success")
                yield Button("Save && Run", id="save_run", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def _collect(self):
        c = self.cfg
        q = lambda i: self.query_one(f"#{i}")
        c["download_dir"] = q("download_dir").value.strip()
        c["music_dir"] = q("music_dir").value.strip()
        c["use_staging_dir"] = q("use_staging_dir").value
        c["staging_dir"] = q("staging_dir").value.strip()
        c["contact_email"] = q("contact_email").value.strip()
        try:
            c["flac_quality"] = max(0, min(12, int(q("flac_quality").value.strip())))
        except ValueError:
            pass
        c["remove_original_after_convert"] = q("remove_original_after_convert").value
        c["downsize_in_place"] = q("downsize_in_place").value
        for key in ("fetch_replaygain", "fetch_lyrics", "review_lyrics_gaps",
                    "remove_asterisks", "translate_lyrics", "normalise_tags",
                    "genre_tags", "fix_capitalisation", "musicbrainz_ids",
                    "downsize", "lossless_check"):
            c["toggles"][key] = q(key).value
        return c

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
            return
        cfg = self._collect()
        if not cfg["download_dir"] or not cfg["music_dir"]:
            self.app.bell()
            self.query_one("#setup-body").mount(
                Static("[red]Downloads folder and music folder are both required.[/red]"))
            return
        pipeline.save_config(cfg)
        if event.button.id == "save_run":
            self.app.pop_screen()
            self.app.push_screen(RunScreen())
        else:
            self.app.pop_screen()


# --------------------------------------------------------------------------
# Run screen - streams run.py --auto, forwards typed lines to its stdin
# --------------------------------------------------------------------------

class RunScreen(Screen):
    """
    Streams `run.py --auto` into a log.

    The log exists in two forms at once:

      - a RichLog, which renders the pipeline's ANSI colour (so the
        highlighted "only this bit changed" diffs actually look like
        diffs), but which you can't select with the mouse;
      - self.lines, a plain-text copy with the colour codes stripped,
        which backs the selectable text view, the clipboard copy and the
        "save to file" button.

    Keeping both means you get colour while reading and real selectable
    text when you need to paste something into a bug report.
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+t", "toggle_select", "Select text"),
        Binding("ctrl+y", "copy_log", "Copy log"),
        Binding("ctrl+s", "save_log", "Save log"),
    ]

    def __init__(self):
        super().__init__()
        self.proc = None
        self.lines: list[str] = []
        self.select_mode = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="log", wrap=True, highlight=False, markup=False)
        # Read-only TextArea: selectable with the mouse and the keyboard,
        # and ctrl+c copies the selection like any other text box.
        text_view = TextArea("", id="log-text", read_only=True)
        text_view.display = False
        yield text_view
        yield Static("", id="log-status")
        yield ProgressBar(id="pipeline-progress", show_eta=False)
        with Horizontal(id="run-input-row"):
            yield Input(placeholder="Type a reply and press Enter (for y/n or missing-tag prompts)...",
                        id="stdin-box", disabled=True)
            yield Button("Select text", id="select", variant="primary")
            yield Button("Copy", id="copy")
            yield Button("Save log", id="save")
            yield Button("Stop", id="stop", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        # Where the running Textual version supports native text selection,
        # turn it on as well - it costs nothing and means plain mouse-drag
        # selection works without toggling into the snapshot view at all.
        for widget_id in ("#log", "#log-status"):
            try:
                widget = self.query_one(widget_id)
            except Exception:
                continue
            if hasattr(widget, "allow_select"):
                try:
                    widget.allow_select = True
                except Exception:
                    pass
        self._status("ctrl+t select text · ctrl+y copy · ctrl+s save")
        self.run_pipeline()

    # -- log plumbing ------------------------------------------------------

    def _status(self, message: str) -> None:
        try:
            self.query_one("#log-status", Static).update(message)
        except Exception:
            pass

    def _emit(self, raw: str) -> None:
        """Write one line to the colour log and the plain-text mirror."""
        # Check if this is a pipeline progress indicator
        if raw.strip().startswith("[[PIPELINE_PROGRESS]]"):
            # Extract stage title for progress tracking
            stage_title = raw.strip()[23:].strip()  # Remove "[[PIPELINE_PROGRESS]] "
            self._update_progress(stage_title)
            return
            
        self.lines.append(ANSI_RE.sub("", raw))
        try:
            log = self.query_one("#log", RichLog)
        except Exception:
            return
        # from_ansi turns the pipeline's escape codes into real styling
        # instead of printing "\x1b[1;33m" at you.
        try:
            log.write(Text.from_ansi(raw))
        except Exception:
            log.write(ANSI_RE.sub("", raw))

    def _update_progress(self, stage_title: str) -> None:
        """Update the visual pipeline progress bar based on stage title."""
        try:
            progress_bar = self.query_one("#pipeline-progress", ProgressBar)
            
            # Simple mapping for now - just show that we are progressing
            # In a more advanced implementation, this could be more sophisticated
            if "1/4" in stage_title:
                progress_bar.progress = 25
            elif "2/4" in stage_title:
                progress_bar.progress = 50
            elif "3/4" in stage_title:
                progress_bar.progress = 75
            elif "4/4" in stage_title:
                progress_bar.progress = 100
                
        except Exception:
            # If no progress bar or other issues, silently continue
            pass

    def log_text(self) -> str:
        return "\n".join(self.lines)

    @work(exclusive=True)
    async def run_pipeline(self) -> None:
        box = self.query_one("#stdin-box", Input)
        self._emit("Starting: python3 run.py --auto\n")

        # The pipeline's stdout is a pipe, not a terminal, so its colour
        # would switch itself off - but this log *does* render colour, so
        # ask for it explicitly.
        env = dict(os.environ)
        env["MUSIC_PIPELINE_FORCE_COLOR"] = "1"
        env.pop("MUSIC_PIPELINE_NO_COLOR", None)
        env.pop("NO_COLOR", None)

        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(SCRIPT_DIR / "run.py"), "--auto",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(SCRIPT_DIR),
            env=env,
        )
        box.disabled = False
        box.focus()
        assert self.proc.stdout is not None

        # readline() waits for a '\n', but a prompt like
        # "Apply this change? (y/n): " deliberately has no newline - it
        # ends with a space so you type on the same line. Reading by line
        # therefore left every question invisible until something else
        # printed after it, which meant answering blind. So: read raw
        # chunks, emit complete lines immediately, and flush whatever is
        # left over once the pipeline goes quiet for a moment (i.e. it is
        # sitting there waiting for your answer).
        pending = ""
        while True:
            try:
                chunk = await asyncio.wait_for(self.proc.stdout.read(4096),
                                               timeout=0.15)
            except asyncio.TimeoutError:
                if pending:
                    self._emit(pending)
                    pending = ""
                continue
            if not chunk:
                break
            pending += chunk.decode(errors="replace")
            *complete, pending = pending.split("\n")
            for line in complete:
                self._emit(line)
        if pending:
            self._emit(pending)

        rc = await self.proc.wait()
        self._emit(f"\n[pipeline exited with code {rc}]")
        box.disabled = True
        self.proc = None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "stdin-box" or self.proc is None or self.proc.stdin is None:
            return
        text = event.value
        self._emit(f"> {text}")
        self.proc.stdin.write((text + "\n").encode())
        event.input.value = ""

    # -- actions -----------------------------------------------------------

    def action_toggle_select(self) -> None:
        """
        Swap between the live colour log and a frozen, selectable copy.

        The text view is deliberately a snapshot: if it kept appending
        while you were dragging a selection, the selection would jump
        around underneath you.
        """
        log = self.query_one("#log", RichLog)
        text_view = self.query_one("#log-text", TextArea)
        button = self.query_one("#select", Button)

        self.select_mode = not self.select_mode
        if self.select_mode:
            try:
                text_view.load_text(self.log_text())
            except Exception:
                text_view.text = self.log_text()
            log.display = False
            text_view.display = True
            text_view.focus()
            button.label = "Live log"
            self._status(f"Selectable snapshot of {len(self.lines)} line(s) - "
                         "drag to select, ctrl+c to copy, ctrl+t for the live log")
        else:
            text_view.display = False
            log.display = True
            button.label = "Select text"
            self._status("Live log - ctrl+t select text · ctrl+y copy · ctrl+s save")

    def action_copy_log(self) -> None:
        text = self.log_text()
        copied = False
        if hasattr(self.app, "copy_to_clipboard"):
            try:
                self.app.copy_to_clipboard(text)
                copied = True
            except Exception:
                copied = False
        if copied:
            self._status(f"Copied {len(self.lines)} line(s) to the clipboard.")
        else:
            # Some terminals refuse clipboard writes; a file always works.
            self.action_save_log()

    def action_save_log(self) -> None:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = SCRIPT_DIR / f"pipeline-log-{stamp}.txt"
        try:
            path.write_text(self.log_text(), encoding="utf-8")
            self._status(f"Saved log to {path}")
        except OSError as e:
            self._status(f"Could not save log: {e}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop" and self.proc is not None:
            self.proc.terminate()
        elif event.button.id == "select":
            self.action_toggle_select()
        elif event.button.id == "copy":
            self.action_copy_log()
        elif event.button.id == "save":
            self.action_save_log()


# --------------------------------------------------------------------------
# Exceptions screen
# --------------------------------------------------------------------------

class ExceptionsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self):
        super().__init__()
        self.store = ExceptionsStore()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Songs the lyrics checker won't nag about (confirmed few/no lyrics).")
        yield DataTable(id="table")
        with Horizontal(id="add-row"):
            yield Input(placeholder="Artist", id="artist")
            yield Input(placeholder="Title", id="title")
            yield Input(placeholder="Reason (optional)", id="reason")
            yield Button("Add", id="add", variant="success")
            yield Button("Remove selected", id="remove", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("Artist", "Title", "Reason")
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        for e in self.store.entries:
            table.add_row(e.get("artist", ""), e.get("title", ""), e.get("reason", ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            artist = self.query_one("#artist", Input).value.strip()
            title = self.query_one("#title", Input).value.strip()
            reason = self.query_one("#reason", Input).value.strip()
            if artist and title:
                self.store.add(artist, title, reason=reason)
                self.query_one("#artist", Input).value = ""
                self.query_one("#title", Input).value = ""
                self.query_one("#reason", Input).value = ""
                self.refresh_table()
        elif event.button.id == "remove":
            table = self.query_one("#table", DataTable)
            if table.cursor_row is not None and table.row_count:
                row = table.get_row_at(table.cursor_row)
                self.store.remove(row[0], row[1])
                self.refresh_table()


class DecisionsScreen(Screen):
    """Review, and undo, the y/n answers the pipeline has remembered."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self):
        super().__init__()
        self.store = DecisionStore()
        self.rows = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Answers the pipeline reuses instead of asking again. "
                     "Remove one to be asked about it next time.")
        yield DataTable(id="decisions")
        with Horizontal(id="decision-row"):
            yield Button("Forget selected", id="forget", variant="error")
            yield Button("Forget all", id="forget-all", variant="error")
        yield Static("", id="decision-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#decisions", DataTable)
        table.add_columns("Answer", "Kind", "Match", "From", "To")
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#decisions", DataTable)
        table.clear()
        self.rows = list(self.store.entries())
        for kind, old, new, decision, matching in self.rows:
            table.add_row("apply" if decision else "skip", kind,
                          "exact" if matching == "exact" else "pattern",
                          old.replace("\n", " / "), new.replace("\n", " / "))
        self.query_one("#decision-status", Static).update(
            f"{len(self.rows)} remembered decision(s) in {self.store.path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "forget-all":
            self.store.forget()
            self.refresh_table()
        elif event.button.id == "forget":
            table = self.query_one("#decisions", DataTable)
            if table.cursor_row is not None and 0 <= table.cursor_row < len(self.rows):
                kind, old, new, _, matching = self.rows[table.cursor_row]
                target = self.store.exact if matching == "exact" else self.store.signature
                target.pop(self.store._key(kind, old, new), None)
                self.store._dirty = True
                self.store.save()
                self.refresh_table()


# --------------------------------------------------------------------------
# Main menu
# --------------------------------------------------------------------------

class MenuScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="menu"):
            yield Static("[b]Music Pipeline[/b]\n", id="menu-title")
            yield Button("Setup (folders + decisions)", id="setup")
            yield Button("Run pipeline", id="run")
            yield Button("Lyrics exceptions list", id="exceptions")
            yield Button("Saved yes/no decisions", id="decisions")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup":
            self.app.push_screen(SetupScreen())
        elif event.button.id == "run":
            cfg = pipeline.load_config()
            if not cfg["download_dir"] or not cfg["music_dir"]:
                self.app.push_screen(SetupScreen())
            else:
                self.app.push_screen(RunScreen())
        elif event.button.id == "exceptions":
            self.app.push_screen(ExceptionsScreen())
        elif event.button.id == "decisions":
            self.app.push_screen(DecisionsScreen())
        elif event.button.id == "quit":
            self.app.exit()


class MusicPipelineApp(App):
    CSS = """
    #menu { align: center middle; height: 100%; }
    #menu Button { width: 40; margin: 1 2; }
    #menu-title { text-align: center; width: 100%; }
    #setup-body { padding: 1 2; }
    #setup-buttons Button { margin-right: 2; }
    #log { height: 1fr; }
    #log-text { height: 1fr; }
    #log-status { height: 1; color: $text-muted; padding: 0 1; }
    #run-input-row { height: 3; }
    #run-input-row Input { width: 1fr; }
    #run-input-row Button { margin-left: 1; }
    #add-row { height: 3; }
    #add-row Input { width: 1fr; margin-right: 1; }
    #table { height: 1fr; }
    #decisions { height: 1fr; }
    #decision-row { height: 3; }
    #decision-row Button { margin-right: 2; }
    #decision-status { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [Binding("q", "quit", "Quit")]

    # Textual 3.0+ honours this for mouse text selection across widgets.
    # Older versions simply ignore the attribute, and the Run screen's
    # ctrl+t snapshot view covers them instead.
    ALLOW_SELECT = True

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())


if __name__ == "__main__":
    MusicPipelineApp().run()
