from __future__ import annotations

import json

import pytest

from keepsake.storage.base import MediaWriteRefused
from keepsake.storage.local import LocalDirBucket
from keepsake.tui.app import NO_TITLE, KeepsakeApp
from keepsake.tui.library import Item, load_items, save_item, titled


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
        items = load_items(bucket)
        assert [i.name for i in items] == ["IMG_0002.MOV", "IMG_0007.MOV"]
        assert titled(items) == 1

    def test_editing_is_staged_until_saved(self, bucket):
        item = load_items(bucket)[0]
        item.edit("title", "Piano recital")

        assert item.dirty
        assert "title" not in json.loads(bucket.get(item.sidecar_key))

        save_item(bucket, item)

        assert not item.dirty
        assert json.loads(bucket.get(item.sidecar_key))["title"] == "Piano recital"

    def test_tags_round_trip_as_a_list(self, bucket):
        item = load_items(bucket)[0]
        item.edit("tags", "piano, school , ")
        save_item(bucket, item)

        assert json.loads(bucket.get(item.sidecar_key))["tags"] == ["piano", "school"]
        assert load_items(bucket)[0].text("tags") == "piano, school"

    def test_clearing_a_field_removes_it(self, bucket):
        item = load_items(bucket)[1]
        assert item.text("title") == "Recital"
        item.edit("title", "")
        save_item(bucket, item)

        assert "title" not in json.loads(bucket.get(item.sidecar_key))

    def test_reverting_an_edit_leaves_nothing_to_save(self, bucket):
        item = load_items(bucket)[1]
        item.edit("title", "Something else")
        item.edit("title", "Recital")
        assert not item.dirty

    def test_save_merges_rather_than_clobbering(self, bucket):
        """SPEC concurrency: the unsafe window is the whole edit session."""
        item = load_items(bucket)[0]
        item.edit("title", "My title")

        # Someone else edits a different field while the form sits open.
        stored = json.loads(bucket.get(item.sidecar_key))
        stored["location"] = "Roosevelt Elementary"
        bucket.put(item.sidecar_key, json.dumps(stored).encode())

        save_item(bucket, item)

        final = json.loads(bucket.get(item.sidecar_key))
        assert final["title"] == "My title"
        assert final["location"] == "Roosevelt Elementary"

    def test_unknown_fields_are_preserved(self, bucket):
        stored = json.loads(bucket.get("2026/05/IMG_0002.MOV.json"))
        stored["future_field"] = {"nested": True}
        bucket.put("2026/05/IMG_0002.MOV.json", json.dumps(stored).encode())

        item = load_items(bucket)[0]
        item.edit("title", "x")
        save_item(bucket, item)

        assert json.loads(bucket.get(item.sidecar_key))["future_field"] == {"nested": True}

    def test_saving_cannot_reach_media(self, bucket):
        item = load_items(bucket)[0]
        item.sidecar_key = item.media_key  # a bug that aims a write at the video
        item.edit("title", "x")
        with pytest.raises(MediaWriteRefused):
            save_item(bucket, item)


class TestApp:
    async def test_lists_the_library(self, bucket):
        app = KeepsakeApp(bucket, label="test-bucket")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#items")
            assert table.row_count == 2
            assert app.tally_text().startswith("1 of 2 titled")

    async def test_typing_a_title_stages_and_saving_writes_it(self, bucket):
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#field-notes").focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused.id == "items"

    async def test_untitled_filter_narrows_the_list(self, bucket):
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#items").focus()
            await pilot.press("q")
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert bucket.head("index.json") is None

    async def test_discarding_leaves_the_sidecar_untouched(self, bucket):
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
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
        app = KeepsakeApp(bucket, label="test-bucket")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("ctrl+q")
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert bucket.head("index.json") is None
