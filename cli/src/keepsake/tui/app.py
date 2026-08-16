"""Terminal UI for reading and writing the human half of a sidecar.

Everything a stub sidecar records is a machine fact. The fields that make an
archive worth keeping -- title, date, tags, location, notes -- can only come
from a person, and typing them one CLI invocation at a time is why the files
are still called IMG_0002.MP4.

`a` uploads (see AddScreen), so this is a complete front end rather than the
second half of one: files in, titles typed, catalog rebuilt on the way out.
The CLI is equally complete on its own via `add` and `set`. Neither should
require the other.

Bucket calls run in thread workers so the interface never blocks on B2.
"""

from __future__ import annotations

from typing import Sequence

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import Regex
from rich.text import Text
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)

from keepsake.core import index as index_mod
from keepsake.core.classify import classify
from keepsake.core.moov import read_movie_header_at
from keepsake.core.survey import compact_bytes, human_bytes, human_duration
from keepsake.core.upload import (
    Candidate,
    PrefixError,
    dated_prefix,
    normalize_prefix,
    parse_paths,
    plan_uploads,
    upload_all,
)
from keepsake.models import new_id
from keepsake.tui.library import (
    EDITABLE,
    FIELD_HINTS,
    RECORDED_AT_PATTERN,
    Item,
    Source,
    load_items,
    open_externally,
    save_item,
    titled,
)

NO_TITLE = "—"

#: Pinned so the app looks the same everywhere. Swap for any name in
#: textual.theme.BUILTIN_THEMES; ctrl+p previews them live.
THEME = "tokyo-night"


def _length_cell(item: Item) -> Text:
    """Runtime when the sidecar records one, file size otherwise.

    `duration_s` is optional in SPEC.md. Files put here by `add` carry one,
    read from their own header; files adopted by `sync` do not yet, so a
    library holds a mix. Size is dimmed to keep the two readable apart -- one
    is how long the video is, the other is merely how big.
    """
    runtime = human_duration(item.payload.get("duration_s"))
    if runtime:
        return Text(runtime)
    return Text(compact_bytes(item.size), style="dim")


class ConfirmQuit(ModalScreen[str]):
    """Asked only when leaving would lose work. Dismisses with the choice."""

    BINDINGS = [
        Binding("s", "choose('save')", "Save & quit"),
        Binding("d", "choose('discard')", "Discard"),
        Binding("escape", "choose('cancel')", "Cancel"),
    ]

    def __init__(self, pending: int):
        super().__init__()
        self.pending = pending

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(
                f"{self.pending} unsaved change{'' if self.pending == 1 else 's'}.",
                id="dialog-text",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("Save & quit", variant="primary", id="save")
                yield Button("Discard", variant="error", id="discard")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#save", Button).focus()

    def action_choose(self, choice: str) -> None:
        self.dismiss(choice)

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "cancel")


class AddScreen(ModalScreen[tuple[str, list[str]]]):
    """Upload files into a library. Dismisses with (profile, keys written).

    The destination prefix is a field rather than a hidden default, because a
    bucket where everything landed at the root is not something anyone chooses
    -- it is what happens when nobody is asked. Leaving it blank means the
    dated layout; the root takes a deliberate `/`.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sources: Sequence[Source], default_profile: str, known_prefixes):
        super().__init__()
        self.sources = list(sources)
        self.profile = default_profile
        self.known_prefixes = list(known_prefixes)
        self.candidates: list[Candidate] = []
        self._uploading = False

    @property
    def bucket(self):
        return dict(self.sources)[self.profile]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-dialog"):
            yield Label("[b]Add media[/]", id="add-heading")

            if len(self.sources) > 1:
                yield Label("library", classes="field-label")
                yield Select(
                    [(name, name) for name, _ in self.sources],
                    value=self.profile,
                    allow_blank=False,
                    id="add-library",
                )

            yield Label("files", classes="field-label")
            yield Input(
                id="add-paths",
                placeholder="drag files in, or type a path or glob",
            )

            yield Label("destination", classes="field-label")
            yield Input(id="add-into", placeholder="YYYY/MM/ from each file's date")
            yield Label("", id="add-into-hint")

            yield Static(id="add-preview")
            yield ProgressBar(id="add-progress", show_eta=False)
            with Horizontal(id="dialog-buttons"):
                yield Button("Upload", variant="primary", id="upload")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#add-progress", ProgressBar).display = False
        self._describe_destination()
        self.query_one("#add-paths", Input).focus()

    # ------------------------------------------------------------- previewing

    def _destination(self) -> str | None:
        """The typed prefix, or None for the dated layout. Raises PrefixError."""
        return normalize_prefix(self.query_one("#add-into", Input).value)

    def _describe_destination(self) -> None:
        """Say where files will land, and warn when that is the bucket root."""
        hint = self.query_one("#add-into-hint", Label)
        try:
            prefix = self._destination()
        except PrefixError as exc:
            hint.update(f"[red]{exc}[/]")
            return

        if prefix is None:
            example = dated_prefix(None)
            known = "  ".join(self.known_prefixes[:6])
            text = f"[dim]{example} — from each file's recording date[/]"
            if known:
                text += f"\n[dim]in this library: {known}[/]"
            hint.update(text)
        elif prefix == "":
            hint.update(
                "[yellow]files will sit at the bucket root[/]\n"
                "[dim]loose alongside index.json, not in a dated folder[/]"
            )
        else:
            hint.update(f"[dim]files will land in {prefix}[/]")

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "add-into":
            self._describe_destination()
        self._preview()

    @on(Select.Changed, "#add-library")
    def _library_changed(self, event: Select.Changed) -> None:
        self.profile = str(event.value)

    def _preview(self) -> None:
        """A local-only preview. The bucket is not consulted until Upload.

        Checking `head` on every keystroke would put a request on B2 for each
        character typed, so the preview shows what can be known from the
        filesystem and the plan proper runs once, in the worker.
        """
        paths = parse_paths(self.query_one("#add-paths", Input).value)
        preview = self.query_one("#add-preview", Static)
        if not paths:
            preview.update("")
            return

        try:
            prefix = self._destination()
        except PrefixError:
            preview.update("")
            return

        lines = []
        for path in paths[:12]:
            if not path.is_file():
                lines.append(f"[red]![/] {path.name}  [red]no such file[/]")
                continue
            size = compact_bytes(path.stat().st_size)
            note = ""
            if prefix is not None:
                where = prefix
            else:
                # Reading the header is two seeks on a local file, so the
                # preview can show the key each file will really get rather
                # than an evasive "somewhere dated".
                header = read_movie_header_at(path)
                recorded = header.recorded_at if header else None
                where = dated_prefix(recorded)
                # Without this a video shot this month and a video with no
                # readable date land in the same folder and look identical.
                note = (
                    f"  [dim]recorded {recorded}[/]"
                    if recorded
                    else "  [yellow]no date in file, filed under today[/]"
                )
            lines.append(f"[green]+[/] {where}{path.name}  [dim]{size}[/]{note}")
        if len(paths) > 12:
            lines.append(f"[dim]… and {len(paths) - 12} more[/]")
        preview.update("\n".join(lines))

    # -------------------------------------------------------------- uploading

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        if not self._uploading:
            self.dismiss((self.profile, []))

    @on(Button.Pressed, "#upload")
    def _upload_pressed(self) -> None:
        if self._uploading:
            return
        paths = parse_paths(self.query_one("#add-paths", Input).value)
        if not paths:
            self.notify("no files given", severity="warning")
            return
        try:
            into = self.query_one("#add-into", Input).value
            normalize_prefix(into)
        except PrefixError as exc:
            self.notify(str(exc), severity="error")
            return

        self._uploading = True
        self.query_one("#upload", Button).disabled = True
        self.query_one("#add-progress", ProgressBar).display = True
        self._run_upload(paths, into)

    @work(thread=True)
    def _run_upload(self, paths, into: str) -> None:
        """Preflight and upload off the UI thread, as every bucket call is."""
        bucket = self.bucket
        candidates = plan_uploads(paths, bucket, into=into)
        viable = [c for c in candidates if c.ok]
        refused = [c for c in candidates if not c.ok]

        for candidate in refused:
            self.app.call_from_thread(
                self.notify, f"{candidate.name}: {candidate.problem}", severity="error"
            )
        if not viable:
            self.app.call_from_thread(self._done, [])
            return

        total = sum(c.size for c in viable)
        done = 0

        def on_progress(candidate: Candidate, seen: int) -> None:
            self.app.call_from_thread(self._set_progress, done + seen, total, candidate.name)

        written: list[str] = []
        for candidate in viable:
            keys, failures = upload_all(
                bucket, [candidate], new_id=new_id, progress=on_progress
            )
            written.extend(keys)
            for failed, reason in failures:
                self.app.call_from_thread(
                    self.notify, f"{failed.name}: {reason}", severity="error"
                )
            done += candidate.size

        self.app.call_from_thread(self._done, written)

    def _set_progress(self, done: int, total: int, name: str) -> None:
        bar = self.query_one("#add-progress", ProgressBar)
        bar.update(total=total, progress=done)
        self.query_one("#add-heading", Label).update(f"[b]Uploading[/] [dim]{name}[/]")

    def _done(self, written: list[str]) -> None:
        if written:
            self.notify(f"uploaded {len(written)} file{'' if len(written) == 1 else 's'}")
        self.dismiss((self.profile, written))


class MediaTable(DataTable):
    """The library list. Right or Enter steps into the form."""

    BINDINGS = [
        # DataTable binds left/right for its column cursor, which does nothing
        # in row-cursor mode, so the keys are free for moving between panes.
        Binding("right,enter", "edit_fields", "Edit", show=False),
    ]

    def action_edit_fields(self) -> None:
        self.app.action_focus_fields()


class FieldInput(Input):
    """A metadata field. Up/Down move between fields, Left at column 0 exits."""

    BINDINGS = [
        Binding("up", "prev_field", show=False),
        Binding("down", "next_field", show=False),
        Binding("left", "back_or_left", show=False),
    ]

    def action_prev_field(self) -> None:
        self.app.focus_field_by_offset(-1)

    def action_next_field(self) -> None:
        self.app.focus_field_by_offset(1)

    def action_back_or_left(self) -> None:
        if self.cursor_position == 0:
            self.app.action_focus_list()
        else:
            self.action_cursor_left()


class KeepsakeApp(App):
    """List on the left, form on the right."""

    CSS_PATH = "app.tcss"
    TITLE = "keepsake"

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("a", "add_media", "Add files"),
        Binding("o", "open_media", "Open in player"),
        Binding("u", "toggle_untitled", "Untitled only"),
        Binding("escape", "focus_list", "Back to list"),
        Binding("q", "quit_asking", "Quit"),
        Binding("ctrl+q", "finish", "Save & quit"),
        # A focused Input consumes printable keys, so the bare letters above
        # only fire from the list. ctrl+o works from anywhere and is hidden to
        # keep the footer readable. There is deliberately no ctrl+u alias:
        # Input binds it to delete-to-start, so it would eat a field's text.
        Binding("ctrl+o", "open_media", "Open in player", show=False),
    ]

    def __init__(
        self,
        sources: Sequence[Source],
        prefix: str = "",
        only: set[str] | None = None,
    ):
        super().__init__()
        self.sources = list(sources)
        self.prefix = prefix
        #: When set, show only these media keys -- `keepsake add` opens the
        #: editor on exactly what it just uploaded.
        self.only = only
        self.items: list[Item] = []
        self.untitled_only = False
        self._current: Item | None = None
        self._populating = False
        #: Profiles whose sidecars were written, so only their catalogs are
        #: rebuilt on the way out.
        self._wrote: set[str] = set()

    @property
    def multi(self) -> bool:
        return len(self.sources) > 1

    @property
    def label(self) -> str:
        if self.multi:
            return f"{len(self.sources)} libraries"
        return self.sources[0][0] if self.sources else "no library"

    # ---------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield MediaTable(id="items", cursor_type="row", zebra_stripes=True)
                yield Label("loading...", id="tally")
            with VerticalScroll(id="right"):
                yield Static(NO_TITLE, id="detail-name")
                for name in EDITABLE:
                    hint = FIELD_HINTS.get(name, "")
                    yield Label(
                        f"{name}  [dim]{hint}[/]" if hint else name,
                        classes="field-label",
                    )
                    yield FieldInput(
                        id=f"field-{name}",
                        placeholder=hint,
                        validators=(
                            [Regex(RECORDED_AT_PATTERN, failure_description="use YYYY-MM-DD")]
                            if name == "recorded_at"
                            else None
                        ),
                        valid_empty=True,
                    )
        yield Footer()

    def on_mount(self) -> None:
        self.theme = THEME
        table = self.query_one("#items", DataTable)
        if self.multi:
            table.add_column("library", key="library")
        table.add_column("media", key="media")
        table.add_column("length", key="length")
        table.add_column("title", key="title")
        table.add_column("date", key="date")
        table.sub_title = self.label
        self.sub_title = self.label
        self._load()

    # ------------------------------------------------------------------ load

    @work(thread=True)
    def _load(self, focus_key: str | None = None) -> None:
        items = load_items(self.sources, self.prefix, self.only)
        self.call_from_thread(self._populate, items, focus_key)

    def _populate(self, items: list[Item], focus_key: str | None = None) -> None:
        self.items = items
        self._refill()
        if focus_key is not None:
            self._focus_media(focus_key)

    def _focus_media(self, media_key: str) -> None:
        """Put the cursor on a media key and open its title for typing."""
        table = self.query_one("#items", DataTable)
        for row, item in enumerate(self._visible()):
            if item.media_key == media_key:
                table.move_cursor(row=row)
                self.query_one(f"#field-{EDITABLE[0]}", Input).focus()
                return

    def _visible(self) -> list[Item]:
        if self.untitled_only:
            return [item for item in self.items if not item.text("title")]
        return self.items

    def _refill(self) -> None:
        table = self.query_one("#items", DataTable)
        table.clear()
        for item in self._visible():
            cells = [
                item.media_key,
                _length_cell(item),
                item.text("title") or NO_TITLE,
                item.text("recorded_at"),
            ]
            if self.multi:
                cells.insert(0, item.profile)
            table.add_row(*cells, key=item.uid)
        self._update_tally()
        if table.row_count:
            table.move_cursor(row=0)
        else:
            self._current = None
            self._show(None)

    def tally_text(self) -> str:
        pending = sum(1 for item in self.items if item.dirty)
        text = f"{titled(self.items)} of {len(self.items)} titled"
        if self.untitled_only:
            text += "  ·  untitled only"
        if pending:
            text += f"  ·  [b]{pending} unsaved[/b]"
        return text

    def _update_tally(self) -> None:
        self.query_one("#tally", Label).update(self.tally_text())

    # ------------------------------------------------------------- selection

    @on(DataTable.RowHighlighted)
    def _row_changed(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value
        self._current = next((i for i in self.items if i.uid == key), None)
        self._show(self._current)

    def _show(self, item: Item | None) -> None:
        # Writing to an Input fires Input.Changed; this flag keeps that from
        # being mistaken for the user typing.
        self._populating = True
        try:
            name = self.query_one("#detail-name", Static)
            if item is None:
                name.update(NO_TITLE)
            elif self.multi:
                name.update(f"{item.name}  [dim]{item.profile} · {human_bytes(item.size)}[/]")
            else:
                name.update(f"{item.name}  [dim]{human_bytes(item.size)}[/]")
            for field in EDITABLE:
                widget = self.query_one(f"#field-{field}", Input)
                widget.value = item.text(field) if item else ""
                widget.disabled = item is None
        finally:
            self._populating = False

    @on(Input.Changed)
    def _field_edited(self, event: Input.Changed) -> None:
        if self._populating or self._current is None:
            return
        field = str(event.input.id or "").removeprefix("field-")
        if field in EDITABLE:
            self._current.edit(field, event.value)
            self._sync_row(self._current)
            self._update_tally()

    def _sync_row(self, item: Item) -> None:
        table = self.query_one("#items", DataTable)
        try:
            table.update_cell(item.uid, "title", item.text("title") or NO_TITLE)
            table.update_cell(item.uid, "date", item.text("recorded_at"))
        except Exception:
            # Row is filtered out of the current view; the tally still updates.
            pass

    # --------------------------------------------------------------- actions

    def action_save(self) -> None:
        if any(item.dirty for item in self.items):
            self._save()
        else:
            self.notify("nothing to save")

    @work(thread=True)
    def _save(self) -> None:
        dirty = [item for item in self.items if item.dirty]
        for item in dirty:
            save_item(item)
            self._wrote.add(item.profile)
        self.call_from_thread(self._saved, len(dirty))

    def _saved(self, count: int) -> None:
        self._update_tally()
        self.notify(f"saved {count} sidecar{'' if count == 1 else 's'}")

    def action_open_media(self) -> None:
        if self._current is None:
            return
        opener = getattr(self._current.bucket, "presigned_url", None)
        if opener is None:
            self.notify("this bucket cannot produce a playable URL", severity="warning")
            return
        try:
            open_externally(opener(self._current.media_key))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.notify(f"could not open: {exc}", severity="error")
        else:
            self.notify(f"opening {self._current.name}")

    def known_prefixes(self, profile: str) -> list[str]:
        """Prefixes this library already uses, most populated first.

        Drawn from the items already loaded, so offering them costs nothing.
        It answers "where does everything else live?" without making anyone
        guess, which is most of what keeps a library from sprawling.
        """
        counts: dict[str, int] = {}
        for item in self.items:
            if item.profile != profile or "/" not in item.media_key:
                continue
            prefix = item.media_key.rsplit("/", 1)[0] + "/"
            counts[prefix] = counts.get(prefix, 0) + 1
        return sorted(counts, key=lambda p: (-counts[p], p))

    def action_add_media(self) -> None:
        if not self.sources:
            return
        profile = self._current.profile if self._current else self.sources[0][0]
        self.push_screen(
            AddScreen(self.sources, profile, self.known_prefixes(profile)),
            self._added,
        )

    def _added(self, result: tuple[str, list[str]] | None) -> None:
        """Reload so the new files appear, and land on the first one's title."""
        if not result:
            return
        profile, written = result
        if not written:
            return
        # That library's catalog is now stale. Marking it here means the
        # rebuild already running on the way out covers the upload too.
        self._wrote.add(profile)
        if self.only is not None:
            self.only = self.only | set(written)
        self._load(focus_key=written[0])

    def action_focus_list(self) -> None:
        self.query_one("#items", DataTable).focus()

    def action_focus_fields(self) -> None:
        if self._current is not None:
            self.query_one(f"#field-{EDITABLE[0]}", Input).focus()

    def focus_field_by_offset(self, delta: int) -> None:
        """Move between fields. Going up past the first returns to the list."""
        ids = [f"field-{name}" for name in EDITABLE]
        focused = self.focused
        if focused is None or focused.id not in ids:
            return
        index = ids.index(focused.id) + delta
        if index < 0:
            self.action_focus_list()
            return
        self.query_one(f"#{ids[min(index, len(ids) - 1)]}", Input).focus()

    def action_toggle_untitled(self) -> None:
        self.untitled_only = not self.untitled_only
        self._refill()

    def action_finish(self) -> None:
        """Save everything and leave, without asking."""
        self._finish()

    def action_quit_asking(self) -> None:
        """Leave. Only interrupts when there is work that would be lost."""
        pending = sum(1 for item in self.items if item.dirty)
        if not pending:
            self._finish()
            return
        self.push_screen(ConfirmQuit(pending), self._quit_choice)

    def _quit_choice(self, choice: str | None) -> None:
        if choice == "save":
            self._finish()
        elif choice == "discard":
            self._finish(save_pending=False)
        # "cancel" or dismissed: stay where we are.

    @work(thread=True)
    def _finish(self, save_pending: bool = True) -> None:
        if save_pending:
            for item in [i for i in self.items if i.dirty]:
                save_item(item)
                self._wrote.add(item.profile)
        # Sidecars are the source of truth; each catalog is rebuilt once, on the
        # way out, rather than on every keystroke-sized save. This runs even when
        # discarding, because earlier saves are already on their buckets and the
        # catalogs have to reflect them. Untouched libraries are left alone.
        for profile, bucket in self.sources:
            if profile in self._wrote:
                result = classify(bucket.list(self.prefix))
                index_mod.write(bucket, index_mod.build_index(result, bucket))
        self.call_from_thread(self.exit)
