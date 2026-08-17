from __future__ import annotations

import json
import shlex

import pytest

from keepsake.core import thumbs as thumbs_mod
from keepsake.core.upload import parse_paths
from keepsake.storage.base import MediaWriteRefused
from keepsake.storage.local import LocalDirBucket
from keepsake.tui.app import (
    IMAGES_AVAILABLE,
    NO_TITLE,
    AddScreen,
    KeepsakeApp,
    _length_cell,
    fit_width,
)
from keepsake.tui.library import Item, is_spec_date, load_items, save_item, titled


def a_jpeg(size: tuple[int, int] = (64, 36)) -> bytes:
    """A real, decodable JPEG.

    The preview pane hands these to Pillow, so a `b"\\xff\\xd8fake"` stand-in
    would only ever exercise the failure path.
    """
    from io import BytesIO

    from PIL import Image as PILImage

    buffer = BytesIO()
    PILImage.new("RGB", size, (90, 120, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = a_jpeg()


def sidecar(file: str, **extra) -> bytes:
    return json.dumps(
        {
            "schema": 1,
            "id": "01HQ8XKPZR4M2N7QVWJT3YFBCD",
            "file": file,
            "uploaded_at": "2026-04-14T02:11:09Z",
            "size_bytes": 100,
            **extra,
        }
    ).encode()


@pytest.fixture
def bucket(tmp_path):
    b = LocalDirBucket(tmp_path, name="test-bucket", readonly=False)
    b.seed("2026/05/IMG_0002.MOV", b"x" * 100)
    b.seed("2026/05/IMG_0002.MOV.json", sidecar("IMG_0002.MOV"))
    b.seed("2026/05/IMG_0007.MOV", b"y" * 200)
    b.seed("2026/05/IMG_0007.MOV.json", sidecar("IMG_0007.MOV", title="Recital"))
    return b


class TestLibrary:
    def test_loads_every_sidecar(self, bucket):
        items = load_items([("test", bucket)])
        assert [i.name for i in items] == ["IMG_0002.MOV", "IMG_0007.MOV"]
        assert titled(items) == 1

    def test_editing_is_staged_until_saved(self, bucket):
        item = load_items([("test", bucket)])[0]
        item.edit("title", "Piano recital")

        assert item.dirty
        assert "title" not in json.loads(bucket.get(item.sidecar_key))

        save_item(item)

        assert not item.dirty
        assert json.loads(bucket.get(item.sidecar_key))["title"] == "Piano recital"

    def test_tags_round_trip_as_a_list(self, bucket):
        item = load_items([("test", bucket)])[0]
        item.edit("tags", "piano, school , ")
        save_item(item)

        assert json.loads(bucket.get(item.sidecar_key))["tags"] == ["piano", "school"]
        assert load_items([("test", bucket)])[0].text("tags") == "piano, school"

    def test_clearing_a_field_removes_it(self, bucket):
        item = load_items([("test", bucket)])[1]
        assert item.text("title") == "Recital"
        item.edit("title", "")
        save_item(item)

        assert "title" not in json.loads(bucket.get(item.sidecar_key))

    def test_reverting_an_edit_leaves_nothing_to_save(self, bucket):
        item = load_items([("test", bucket)])[1]
        item.edit("title", "Something else")
        item.edit("title", "Recital")
        assert not item.dirty

    def test_save_merges_rather_than_clobbering(self, bucket):
        """SPEC concurrency: the unsafe window is the whole edit session."""
        item = load_items([("test", bucket)])[0]
        item.edit("title", "My title")

        # Someone else edits a different field while the form sits open.
        stored = json.loads(bucket.get(item.sidecar_key))
        stored["location"] = "Roosevelt Elementary"
        bucket.put(item.sidecar_key, json.dumps(stored).encode())

        save_item(item)

        final = json.loads(bucket.get(item.sidecar_key))
        assert final["title"] == "My title"
        assert final["location"] == "Roosevelt Elementary"

    def test_unknown_fields_are_preserved(self, bucket):
        stored = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        stored["future_field"] = {"nested": True}
        bucket.put("2026/05/IMG_0002.MOV.json", json.dumps(stored).encode())

        item = load_items([("test", bucket)])[0]
        item.edit("title", "x")
        save_item(item)

        assert json.loads(bucket.get(item.sidecar_key))["future_field"] == {"nested": True}

    def test_saving_cannot_reach_media(self, bucket):
        item = load_items([("test", bucket)])[0]
        item.sidecar_key = item.media_key  # a bug that aims a write at the video
        item.edit("title", "x")
        with pytest.raises(MediaWriteRefused):
            save_item(item)


class TestApp:
    async def test_lists_the_library(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#items")
            assert table.row_count == 2
            assert app.tally_text().startswith("1 of 2 titled")

    async def test_typing_a_title_stages_and_saving_writes_it(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Spring concert"
            await pilot.pause()
            assert app.items[0].dirty

            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            await pilot.pause()

        written = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        assert written["title"] == "Spring concert"

    async def test_arrows_move_between_list_and_fields(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#items").focus()
            await pilot.pause()

            await pilot.press("right")          # into the form
            await pilot.pause()
            assert app.focused.id == "field-title"

            await pilot.press("down")           # next field
            await pilot.pause()
            assert app.focused.id == "field-recorded_at"

            await pilot.press("up")             # back up
            await pilot.pause()
            assert app.focused.id == "field-title"

            await pilot.press("left")           # at column 0 -> back to list
            await pilot.pause()
            assert app.focused.id == "items"

    async def test_left_inside_text_moves_the_cursor_not_the_focus(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            field = app.query_one("#field-title")
            field.focus()
            await pilot.pause()
            await pilot.press("a", "b")
            await pilot.pause()
            assert field.cursor_position == 2

            await pilot.press("left")
            await pilot.pause()
            assert app.focused.id == "field-title"
            assert field.cursor_position == 1

    async def test_letter_bindings_do_not_hijack_typing(self, bucket):
        """`o` and `u` are actions from the list but literal text in a field."""
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").focus()
            await pilot.pause()
            await pilot.press("o", "u", "t")
            await pilot.pause()

            assert app.query_one("#field-title").value == "out"
            assert app.untitled_only is False

    async def test_escape_returns_to_the_list(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#field-notes").focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused.id == "items"

    async def test_untitled_filter_narrows_the_list(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#items").row_count == 2

            app.query_one("#items").focus()
            await pilot.pause()
            await pilot.press("u")
            await pilot.pause()
            assert app.query_one("#items").row_count == 1

    async def test_quitting_rebuilds_the_catalog(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#field-title").value = "Spring concert"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await app.workers.wait_for_complete()
            await pilot.pause()

        catalog = json.loads(bucket.get("index.json"))
        assert catalog["count"] == 2
        titles = {item["path"]: item.get("title") for item in catalog["items"]}
        assert titles["2026/05/IMG_0002.MOV"] == "Spring concert"

    async def test_quitting_clean_does_not_ask(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#items").focus()
            await pilot.press("q")
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert bucket.head("index.json") is None

    async def test_discarding_leaves_the_sidecar_untouched(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Typed by mistake"
            await pilot.pause()

            app.query_one("#items").focus()
            await pilot.press("q")
            await pilot.pause()
            await pilot.press("d")              # discard
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert "title" not in json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))

    async def test_cancelling_stays_in_the_app_with_edits_intact(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Keep me"
            await pilot.pause()

            app.query_one("#items").focus()
            await pilot.press("q")
            await pilot.pause()
            await pilot.press("escape")         # cancel
            await pilot.pause()

            assert app.is_running
            assert app.items[0].dirty
            assert app.items[0].text("title") == "Keep me"

    async def test_quit_dialog_can_save(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Spring concert"
            await pilot.pause()

            app.query_one("#items").focus()
            await pilot.press("q")
            await pilot.pause()
            await pilot.press("s")              # save & quit
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))["title"] == "Spring concert"

    async def test_discard_still_rebuilds_the_catalog_after_an_earlier_save(self, bucket):
        """Edits saved earlier are already on the bucket; the index must match."""
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Committed"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-location").value = "Discarded"
            await pilot.pause()

            app.query_one("#items").focus()
            await pilot.press("q")
            await pilot.pause()
            await pilot.press("d")
            await app.workers.wait_for_complete()
            await pilot.pause()

        stored = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        assert stored["title"] == "Committed"
        assert "location" not in stored
        assert json.loads(bucket.get("index.json"))["count"] == 2

    async def test_no_catalog_write_when_nothing_changed(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("ctrl+q")
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert bucket.head("index.json") is None


class TestMultipleLibraries:
    @pytest.fixture
    def two(self, tmp_path):
        made = []
        for name in ("jane", "john"):
            b = LocalDirBucket(tmp_path / name, name=f"media-{name}", readonly=False)
            # Deliberately the same key in both, to catch row-identity bugs.
            b.seed("2026/05/IMG_0002.MOV", b"x" * 100)
            b.seed("2026/05/IMG_0002.MOV.json", sidecar("IMG_0002.MOV"))
            made.append((name, b))
        return made

    def test_items_carry_their_own_library(self, two):
        items = load_items(two)
        assert [i.profile for i in items] == ["jane", "john"]
        assert len({i.uid for i in items}) == 2, "same key in two buckets must not collide"

    def test_a_save_goes_back_to_its_own_bucket(self, two):
        items = load_items(two)
        items[1].edit("title", "John's clip")
        save_item(items[1])

        jane, john = two[0][1], two[1][1]
        assert "title" not in json.loads(jane.get("2026/05/IMG_0002.MOV.json"))
        assert json.loads(john.get("2026/05/IMG_0002.MOV.json"))["title"] == "John's clip"

    async def test_a_library_column_appears_only_when_several_are_open(self, two, bucket):
        app = KeepsakeApp(two)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#items")
            assert table.row_count == 2
            assert [c.label.plain for c in table.columns.values()][0] == "library"

        single = KeepsakeApp([("test", bucket)])
        async with single.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            labels = [c.label.plain for c in single.query_one("#items").columns.values()]
            assert "library" not in labels

    async def test_only_touched_libraries_get_a_new_catalog(self, two):
        app = KeepsakeApp(two)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # Row 0 is jane's; edit it and leave john's alone.
            app.query_one("#field-title").value = "Only jane"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await app.workers.wait_for_complete()
            await pilot.pause()

        jane, john = two[0][1], two[1][1]
        assert json.loads(jane.get("index.json"))["count"] == 1
        assert john.head("index.json") is None, "untouched library must not be rewritten"


class TestLengthColumn:
    def test_runtime_wins_when_the_sidecar_records_one(self, tmp_path):
        b = LocalDirBucket(tmp_path, readonly=False)
        b.seed("clip.MOV", b"x" * 65_413_818)
        b.seed("clip.MOV.json", sidecar("clip.MOV", duration_s=222))
        cell = _length_cell(load_items([("t", b)])[0])
        assert cell.plain == "3:42"
        assert cell.style == ""

    def test_size_is_the_fallback_and_is_dimmed(self, tmp_path):
        b = LocalDirBucket(tmp_path, readonly=False)
        b.seed("clip.MOV", b"x" * 65_413_818)
        b.seed("clip.MOV.json", sidecar("clip.MOV"))
        cell = _length_cell(load_items([("t", b)])[0])
        assert cell.plain == "62 MB"
        assert cell.style == "dim"

    def test_hours_are_shown(self, tmp_path):
        b = LocalDirBucket(tmp_path, readonly=False)
        b.seed("clip.MOV", b"x")
        b.seed("clip.MOV.json", sidecar("clip.MOV", duration_s=3733))
        assert _length_cell(load_items([("t", b)])[0]).plain == "1:02:13"

    def test_a_nonsense_duration_falls_back_to_size(self, tmp_path):
        b = LocalDirBucket(tmp_path, readonly=False)
        b.seed("clip.MOV", b"x" * 2048)
        b.seed("clip.MOV.json", sidecar("clip.MOV", duration_s="not a number"))
        assert _length_cell(load_items([("t", b)])[0]).plain == "2.0 KB"

    async def test_the_column_is_present(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            labels = [c.label.plain for c in app.query_one("#items").columns.values()]
            assert labels == ["media", "length", "title", "date"]


class TestFieldHints:
    async def test_recorded_at_advertises_its_format(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#field-recorded_at").placeholder == "YYYY-MM-DD"
            labels = [str(l.render()) for l in app.query(".field-label")]
            assert any("YYYY-MM-DD" in text for text in labels)

    async def test_an_off_spec_date_is_marked_invalid(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            field = app.query_one("#field-recorded_at")

            field.value = "05/22/26"          # what a person actually types
            await pilot.pause()
            assert field.has_class("-invalid")

            field.value = "2026-05-22"
            await pilot.pause()
            assert not field.has_class("-invalid")

    async def test_an_empty_date_is_not_an_error(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            field = app.query_one("#field-recorded_at")
            field.value = ""
            await pilot.pause()
            assert not field.has_class("-invalid")

    async def test_other_fields_are_unconstrained(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            field = app.query_one("#field-title")
            field.value = "anything at all 05/22/26"
            await pilot.pause()
            assert not field.has_class("-invalid")


class TestAddScreen:
    """Uploading from the TUI, including where the destination field steers."""

    async def test_a_opens_the_add_screen(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, AddScreen)

    async def test_destination_defaults_to_the_dated_layout(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()

            assert app.screen.query_one("#add-into").value == ""
            hint = str(app.screen.query_one("#add-into-hint").content)
            assert "recording date" in hint

    async def test_a_lone_slash_warns_about_the_bucket_root(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()

            app.screen.query_one("#add-into").value = "/"
            await pilot.pause()

            hint = str(app.screen.query_one("#add-into-hint").content)
            assert "bucket root" in hint
            # Discouraged, never blocked. SPEC allows it.
            assert not app.screen.query_one("#upload").disabled

    async def test_preview_resolves_the_real_dated_key(self, bucket, tmp_path):
        """Not "somewhere dated" -- the key the file will actually get."""
        from datetime import datetime, timezone

        from test_moov import movie, mvhd_v0, seconds_since_1904

        source = tmp_path / "incoming"
        source.mkdir()
        clip = source / "tape.mov"
        stamp = seconds_since_1904(datetime(2019, 3, 7, tzinfo=timezone.utc))
        clip.write_bytes(movie(mvhd_v0(creation=stamp, duration=600)).getvalue())

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()

            app.screen.query_one("#add-paths").value = str(clip)
            await pilot.pause()

            preview = str(app.screen.query_one("#add-preview").content)
            assert "2019/03/tape.mov" in preview
            assert "recorded 2019-03-07" in preview

    async def test_preview_flags_a_file_with_no_readable_date(self, bucket, tmp_path):
        from test_moov import movie, mvhd_v0

        source = tmp_path / "incoming"
        source.mkdir()
        clip = source / "undated.mov"
        clip.write_bytes(movie(mvhd_v0(creation=0, duration=600)).getvalue())

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()

            app.screen.query_one("#add-paths").value = str(clip)
            await pilot.pause()

            preview = str(app.screen.query_one("#add-preview").content)
            assert "no date in file, filed under today" in preview

    async def test_offers_the_prefixes_the_library_already_uses(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.known_prefixes("test") == ["2026/05/"]

    async def test_uploading_adds_the_file_to_the_list(self, bucket, tmp_path):
        source = tmp_path / "incoming"
        source.mkdir()
        clip = source / "new-clip.mov"
        clip.write_bytes(b"z" * 300)

        app = KeepsakeApp([("test", bucket)])
        # Big enough that the dialog's buttons are on screen for the click.
        async with app.run_test(size=(100, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#items").row_count == 2

            await pilot.press("a")
            await pilot.pause()
            app.screen.query_one("#add-paths").value = str(clip)
            app.screen.query_one("#add-into").value = "2026/08/"
            await pilot.pause()

            await pilot.click("#upload")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#items").row_count == 3

        assert bucket.get("2026/08/new-clip.mov") == b"z" * 300
        assert json.loads(bucket.get("2026/08/new-clip.mov.json"))["file"] == "new-clip.mov"

    async def test_a_refused_file_does_not_dismiss_or_write(self, bucket, tmp_path):
        """A name with no extension cannot be catalogued, so it never lands."""
        source = tmp_path / "incoming"
        source.mkdir()
        bad = source / "no-extension"
        bad.write_bytes(b"z" * 300)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test(size=(100, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            app.screen.query_one("#add-paths").value = str(bad)
            await pilot.pause()

            await pilot.click("#upload")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#items").row_count == 2

        assert bucket.head("no-extension") is None

    async def test_drag_and_dropped_paths_are_unquoted(self, tmp_path):
        """Finder pastes shell-quoted paths; a space must survive the trip."""
        spaced = tmp_path / "My Movies"
        spaced.mkdir()
        clip = spaced / "day one.mov"
        clip.write_bytes(b"x" * 64)

        assert parse_paths(shlex.quote(str(clip))) == [clip]
        assert parse_paths(str(clip).replace(" ", "\\ ")) == [clip]


class TestThumbnailKey:
    """`t` on the highlighted row. The TUI has to finish this job on its own --
    sending someone to the shell for `sync --thumbs` would make it half a front
    end."""

    async def test_renders_and_records_the_thumbnail(self, bucket, monkeypatch):
        """ffmpeg is stubbed here rather than run. What is under test is the
        wiring -- which file, which key, and whether the row refreshes -- and
        the rendering itself is covered against real ffmpeg in test_thumbs.py.
        """
        monkeypatch.setattr(thumbs_mod, "ffmpeg_available", lambda: True)
        monkeypatch.setattr(thumbs_mod, "require_ffmpeg", lambda: None)
        monkeypatch.setattr(
            thumbs_mod,
            "render",
            lambda url, dest, **kw: dest.write_bytes(JPEG),
        )
        monkeypatch.setattr(thumbs_mod, "probe_duration", lambda url, **kw: 222.0)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("t")
            await app.workers.wait_for_complete()
            await pilot.pause()

            # The length column swaps size for runtime without a reload.
            table = app.query_one("#items")
            assert table.get_cell(app.items[0].uid, "length").plain == "3:42"

        assert bucket.get("2026/05/IMG_0002.MOV.jpg") == JPEG
        stored = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        assert stored["thumbnail"] == "IMG_0002.MOV.jpg"
        assert stored["duration_s"] == 222.0

    async def test_says_so_when_ffmpeg_is_not_installed(self, bucket, monkeypatch):
        monkeypatch.setattr(thumbs_mod, "ffmpeg_available", lambda: False)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("t")
            await pilot.pause()

            assert any(
                "brew install ffmpeg" in str(note.message)
                for note in app._notifications
            )

        assert bucket.head("2026/05/IMG_0002.MOV.jpg") is None

    async def test_an_unsaved_title_survives_the_render(self, bucket, monkeypatch):
        """The render writes to the same sidecar the editor has open, so the
        refresh afterwards has to touch only the two fields it could have
        changed."""
        monkeypatch.setattr(thumbs_mod, "ffmpeg_available", lambda: True)
        monkeypatch.setattr(thumbs_mod, "require_ffmpeg", lambda: None)
        monkeypatch.setattr(
            thumbs_mod,
            "render",
            lambda url, dest, **kw: dest.write_bytes(JPEG),
        )
        monkeypatch.setattr(thumbs_mod, "probe_duration", lambda url, **kw: 222.0)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#field-title").value = "Spring concert"
            await pilot.pause()

            await pilot.press("t")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.items[0].dirty
            assert app.items[0].text("title") == "Spring concert"

            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            await pilot.pause()

        stored = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        assert stored["title"] == "Spring concert"
        assert stored["thumbnail"] == "IMG_0002.MOV.jpg"


class TestFitWidth:
    """Sizing the preview so it is letterboxed rather than stretched.

    Terminal cells are twice as tall as they are wide, so `cell` has to be
    carried through every comparison — that factor of two is precisely the
    distortion this exists to avoid. 10x20 is what `get_cell_size()` reports
    on this machine.
    """

    CELL = (10, 20)

    def rows(self, pixels, width_cells) -> float:
        """The height the widget will derive from a given width."""
        image_width, image_height = pixels
        return (width_cells * self.CELL[0] * image_height) / (image_width * self.CELL[1])

    def test_a_landscape_clip_uses_the_full_width(self):
        # 640x360 at 40 cells is ~11 rows, comfortably under the cap.
        assert fit_width((640, 360), 40, self.CELL, max_rows=14) == 40

    def test_a_portrait_clip_is_narrowed_rather_than_squashed(self):
        """Phone video is the case that forced this. At full pane width a
        1080x1920 clip would be 35 rows tall and swallow the form."""
        width = fit_width((1080, 1920), 40, self.CELL, max_rows=14)

        assert width < 40
        assert self.rows((1080, 1920), width) <= 14

    def test_the_result_keeps_the_aspect_ratio(self):
        for pixels in ((1920, 1080), (1080, 1920), (640, 640), (720, 480)):
            width = fit_width(pixels, 40, self.CELL, max_rows=14)
            assert 0 < width <= 40
            assert self.rows(pixels, width) <= 14 + 1e-9

    def test_a_square_clip_is_narrowed_too(self):
        # 1:1 in pixels is 2:1 in cells, so 40 cells wide would be 20 rows.
        width = fit_width((600, 600), 40, self.CELL, max_rows=14)
        assert width == 28

    def test_a_narrow_pane_is_never_exceeded(self):
        assert fit_width((1920, 1080), 12, self.CELL, max_rows=14) == 12

    def test_degenerate_input_does_not_divide_by_zero(self):
        assert fit_width((0, 0), 40, self.CELL) == 40
        assert fit_width((640, 360), 0, self.CELL) == 1


@pytest.mark.skipif(not IMAGES_AVAILABLE, reason="textual-image is not installed")
class TestThumbnailPane:
    """The preview beside the form. What is asserted is which state the pane is
    in -- image, note, or hidden -- since whether pixels reach the terminal
    depends on the terminal and cannot be checked from a test."""

    async def test_shows_the_image_when_the_bucket_has_one(self, bucket):
        bucket.seed("2026/05/IMG_0002.MOV.jpg", JPEG)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.items[0].thumbnail_key == "2026/05/IMG_0002.MOV.jpg"
            image = app.query_one("#thumb")
            assert image.display is True
            assert image.image is not None
            assert str(app.query_one("#thumb-note").content) == ""

    async def test_says_how_to_make_one_when_there_is_none(self, bucket):
        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#thumb").display is False
            assert "press t" in str(app.query_one("#thumb-note").content)

    async def test_an_unreadable_image_does_not_take_down_the_editor(self, bucket):
        """A bucket is writable by other things, so a truncated or mislabelled
        thumbnail is entirely possible. It is derived data -- report it in the
        pane and carry on."""
        bucket.seed("2026/05/IMG_0002.MOV.jpg", b"\xff\xd8not really a jpeg")

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#thumb").display is False
            assert "not a readable image" in str(
                app.query_one("#thumb-note").content
            )
            # The rest of the editor still works.
            app.query_one("#field-title").value = "Still editable"
            await pilot.pause()
            assert app.items[0].dirty

    async def test_a_portrait_thumbnail_is_narrowed_not_stretched(self, bucket):
        """End to end: the pane must apply `fit_width`, not hand the widget the
        whole pane and let it squash a phone clip into a landscape box."""
        bucket.seed("2026/05/IMG_0002.MOV.jpg", a_jpeg((1080, 1920)))

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test(size=(100, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            image = app.query_one("#thumb")
            pane = app.query_one("#right").content_size.width
            assert image.display is True
            # Narrower than the pane, which is what letterboxing looks like
            # from here.
            assert image.styles.width.value < pane
            assert image.outer_size.height <= 14

    async def test_a_landscape_thumbnail_fills_the_pane(self, bucket):
        bucket.seed("2026/05/IMG_0002.MOV.jpg", a_jpeg((1920, 1080)))

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test(size=(100, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            image = app.query_one("#thumb")
            assert image.display is True
            assert image.styles.width.value == app.query_one("#right").content_size.width

    async def test_a_landscape_clip_recovers_the_full_width_after_a_portrait_one(
        self, bucket
    ):
        """The preview must not ratchet smaller. Narrowing the image narrows
        its own container, so sizing off that would leave every clip after a
        portrait one stuck at the portrait width."""
        bucket.seed("2026/05/IMG_0002.MOV.jpg", a_jpeg((1080, 1920)))  # portrait
        bucket.seed("2026/05/IMG_0007.MOV.jpg", a_jpeg((1920, 1080)))  # landscape

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test(size=(100, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            narrowed = app.query_one("#thumb").styles.width.value

            await pilot.press("down")
            await app.workers.wait_for_complete()
            await pilot.pause()

            pane = app.query_one("#right").content_size.width
            assert narrowed < pane
            assert app.query_one("#thumb").styles.width.value == pane

    async def test_moving_between_rows_swaps_the_image(self, bucket):
        bucket.seed("2026/05/IMG_0007.MOV.jpg", JPEG)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # First row has no thumbnail...
            assert app.query_one("#thumb").display is False

            await pilot.press("down")
            await app.workers.wait_for_complete()
            await pilot.pause()

            # ...the second does.
            assert app.items[1].media_key == "2026/05/IMG_0007.MOV"
            assert app.query_one("#thumb").display is True

    async def test_rendering_one_fills_the_pane_immediately(
        self, bucket, monkeypatch
    ):
        """`t` does not reload the library, so the pane has to be told about
        the key that was just written."""
        monkeypatch.setattr(thumbs_mod, "ffmpeg_available", lambda: True)
        monkeypatch.setattr(thumbs_mod, "require_ffmpeg", lambda: None)
        monkeypatch.setattr(
            thumbs_mod, "render", lambda url, dest, **kw: dest.write_bytes(JPEG)
        )
        monkeypatch.setattr(thumbs_mod, "probe_duration", lambda url, **kw: 12.0)

        app = KeepsakeApp([("test", bucket)])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#thumb").display is False

            await pilot.press("t")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#thumb").display is True


@pytest.mark.parametrize(
    "text,valid",
    [
        ("2026-05-22", True),
        ("2026-05-22T14:30:00Z", True),
        ("2026-05-22T14:30:00+09:00", True),
        ("", True),
        ("05/22/26", False),
        ("05/22/2026", False),
        ("5/22/26", False),
        ("May 22 2026", False),
        ("2026-5-2", False),
    ],
)
def test_is_spec_date(text, valid):
    assert is_spec_date(text) is valid
