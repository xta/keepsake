"""Terminal UI for reading and writing the human half of a sidecar.

Everything a stub sidecar records is a machine fact. The fields that make an
archive worth keeping -- title, date, tags, location, notes -- can only come
from a person, and typing them one CLI invocation at a time is why the files
are still called IMG_0002.MP4.

Bucket calls run in thread workers so the interface never blocks on B2.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from keepsake.core import index as index_mod
from keepsake.core.classify import classify
from keepsake.core.survey import human_bytes
from keepsake.storage.base import Bucket
from keepsake.tui.library import EDITABLE, Item, load_items, open_externally, save_item, titled

NO_TITLE = "—"


class KeepsakeApp(App):
    """List on the left, form on the right."""

    CSS_PATH = "app.tcss"
    TITLE = "keepsake"

    BINDINGS = [
        # Deliberately all ctrl-chorded: single letters would be swallowed by
        # whichever Input has focus.
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+o", "open_media", "Open in player"),
        Binding("ctrl+u", "toggle_untitled", "Untitled only"),
        Binding("ctrl+q", "finish", "Save & quit"),
    ]

    def __init__(self, bucket: Bucket, label: str = "", prefix: str = ""):
        super().__init__()
        self.bucket = bucket
        self.label = label or getattr(bucket, "name", "bucket")
        self.prefix = prefix
        self.items: list[Item] = []
        self.untitled_only = False
        self._current: Item | None = None
        self._populating = False
        self._wrote_anything = False

    # ---------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield DataTable(id="items", cursor_type="row", zebra_stripes=True)
                yield Label("loading...", id="tally")
            with VerticalScroll(id="right"):
                yield Static(NO_TITLE, id="detail-name")
                for name in EDITABLE:
                    yield Label(name, classes="field-label")
                    yield Input(id=f"field-{name}", placeholder=name)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#items", DataTable)
        table.add_column("media", key="media")
        table.add_column("title", key="title")
        table.add_column("date", key="date")
        table.sub_title = self.label
        self.sub_title = self.label
        self._load()

    # ------------------------------------------------------------------ load

    @work(thread=True)
    def _load(self) -> None:
        items = load_items(self.bucket, self.prefix)
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
            table.add_row(
                item.media_key,
                item.text("title") or NO_TITLE,
                item.text("recorded_at"),
                key=item.media_key,
            )
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
        self._current = next((i for i in self.items if i.media_key == key), None)
        self._show(self._current)

    def _show(self, item: Item | None) -> None:
        # Writing to an Input fires Input.Changed; this flag keeps that from
        # being mistaken for the user typing.
        self._populating = True
        try:
            name = self.query_one("#detail-name", Static)
            name.update(
                f"{item.name}  ({human_bytes(item.size)})" if item else NO_TITLE
            )
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
            table.update_cell(item.media_key, "title", item.text("title") or NO_TITLE)
            table.update_cell(item.media_key, "date", item.text("recorded_at"))
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
            save_item(self.bucket, item)
        self.call_from_thread(self._saved, len(dirty))

    def _saved(self, count: int) -> None:
        self._wrote_anything = self._wrote_anything or bool(count)
        self._update_tally()
        self.notify(f"saved {count} sidecar{'' if count == 1 else 's'}")

    def action_open_media(self) -> None:
        if self._current is None:
            return
        opener = getattr(self.bucket, "presigned_url", None)
        if opener is None:
            self.notify("this bucket cannot produce a playable URL", severity="warning")
            return
        try:
            open_externally(opener(self._current.media_key))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.notify(f"could not open: {exc}", severity="error")
        else:
            self.notify(f"opening {self._current.name}")

    def action_toggle_untitled(self) -> None:
        self.untitled_only = not self.untitled_only
        self._refill()

    def action_finish(self) -> None:
        self._finish()

    @work(thread=True)
    def _finish(self) -> None:
        for item in [i for i in self.items if i.dirty]:
            save_item(self.bucket, item)
            self._wrote_anything = True
        if self._wrote_anything:
            # Sidecars are the source of truth; the catalog is rebuilt once, on
            # the way out, rather than on every keystroke-sized save.
            result = classify(self.bucket.list(self.prefix))
            index_mod.write(self.bucket, index_mod.build_index(result, self.bucket))
        self.call_from_thread(self.exit)
