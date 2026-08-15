"""Terminal UI for reading and writing the human half of a sidecar.

Everything a stub sidecar records is a machine fact. The fields that make an
archive worth keeping -- title, date, tags, location, notes -- can only come
from a person, and typing them one CLI invocation at a time is why the files
are still called IMG_0002.MP4.

Bucket calls run in thread workers so the interface never blocks on B2.
"""

from __future__ import annotations

from typing import Sequence

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from rich.text import Text
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

from keepsake.core import index as index_mod
from keepsake.core.classify import classify
from keepsake.core.survey import compact_bytes, human_bytes, human_duration
from keepsake.tui.library import (
    EDITABLE,
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

    `duration_s` is optional in SPEC.md and nothing populates it yet, so most
    rows fall back to size. Size is dimmed to keep the two readable apart --
    one is how long the video is, the other is merely how big.
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

    def __init__(self, sources: Sequence[Source], prefix: str = ""):
        super().__init__()
        self.sources = list(sources)
        self.prefix = prefix
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
                    yield Label(name, classes="field-label")
                    yield FieldInput(id=f"field-{name}", placeholder=name)
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
    def _load(self) -> None:
        items = load_items(self.sources, self.prefix)
        self.call_from_thread(self._populate, items)

    def _populate(self, items: list[Item]) -> None:
        self.items = items
        self._refill()

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
