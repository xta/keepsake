"""Writing into a sidecar that already exists.

The merge is the whole point of this module: SPEC.md's concurrency rule says a
writer must re-read immediately before writing and apply fields one at a time,
and every test here is some form of "did the field somebody else wrote
survive".
"""

from __future__ import annotations

import json

import pytest

from keepsake.core.adopt import sidecar_payload
from keepsake.core.sidecar import (
    FIELD_ORDER,
    SidecarUnreadable,
    backfill_sidecar,
    canonical,
    merge_sidecar,
    missing_fields,
    read_sidecar,
)
from keepsake.storage.local import LocalDirBucket

KEY = "2026/05/clip.mp4.json"


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


def seed(bucket, **extra) -> dict:
    payload = {
        "schema": 1,
        "id": "01a0098c-ebfd-7e9f-bac0-ca39f3495b09",
        "file": "clip.mp4",
        "uploaded_at": "2026-05-01T00:00:00Z",
        **extra,
    }
    bucket.seed(KEY, json.dumps(payload).encode())
    return payload


def stored(bucket) -> dict:
    return json.loads(bucket.get(KEY))


class TestMerge:
    def test_adds_a_field_and_leaves_the_rest_alone(self, bucket):
        seed(bucket, title="Recital")

        merge_sidecar(bucket, KEY, {"thumbnail": "clip.mp4.jpg"})

        after = stored(bucket)
        assert after["thumbnail"] == "clip.mp4.jpg"
        assert after["title"] == "Recital"
        assert after["id"] == "01a0098c-ebfd-7e9f-bac0-ca39f3495b09"

    def test_none_removes_a_field(self, bucket):
        seed(bucket, title="Recital")

        merge_sidecar(bucket, KEY, {"title": None})

        assert "title" not in stored(bucket)

    def test_unknown_fields_are_carried_through(self, bucket):
        """SPEC.md: a writer that does not recognise a field preserves it."""
        seed(bucket, curator_rating=5, provenance={"reel": "7"})

        merge_sidecar(bucket, KEY, {"title": "Recital"})

        after = stored(bucket)
        assert after["curator_rating"] == 5
        assert after["provenance"] == {"reel": "7"}

    def test_a_field_written_meanwhile_survives(self, bucket):
        """The reason the stored object is re-read rather than PUT wholesale.

        `loaded` stands in for a payload read at the start of an edit session.
        A title typed against it must not carry the rest of that stale copy
        back to the bucket.
        """
        loaded = seed(bucket)
        seed(bucket, location="Roosevelt Elementary")  # someone else, meanwhile

        merge_sidecar(bucket, KEY, {"title": "Recital"}, fallback=loaded)

        after = stored(bucket)
        assert after["title"] == "Recital"
        assert after["location"] == "Roosevelt Elementary"

    def test_only_if_absent_leaves_an_existing_value(self, bucket):
        seed(bucket, duration_s=412.0)

        merge_sidecar(
            bucket,
            KEY,
            {"thumbnail": "clip.mp4.jpg", "duration_s": 99.0},
            only_if_absent=("duration_s",),
        )

        after = stored(bucket)
        assert after["duration_s"] == 412.0
        assert after["thumbnail"] == "clip.mp4.jpg"

    def test_only_if_absent_fills_a_missing_value(self, bucket):
        seed(bucket)

        merge_sidecar(bucket, KEY, {"duration_s": 99.0}, only_if_absent=("duration_s",))

        assert stored(bucket)["duration_s"] == 99.0

    def test_an_unreadable_sidecar_falls_back_when_offered_one(self, bucket):
        bucket.seed(KEY, b"{not json")

        merge_sidecar(
            bucket, KEY, {"title": "Recital"}, fallback={"schema": 1, "id": "x"}
        )

        after = stored(bucket)
        assert after == {"schema": 1, "id": "x", "title": "Recital"}

    def test_an_unreadable_sidecar_raises_without_a_fallback(self, bucket):
        """Better to leave the broken object for `check` than to overwrite it
        with a sidecar missing every field SPEC.md requires."""
        bucket.seed(KEY, b"{not json")

        with pytest.raises(SidecarUnreadable):
            merge_sidecar(bucket, KEY, {"title": "Recital"})

    def test_a_json_scalar_is_not_a_sidecar(self, bucket):
        bucket.seed(KEY, b"42")

        with pytest.raises(SidecarUnreadable):
            merge_sidecar(bucket, KEY, {"title": "Recital"})


class TestBackfill:
    def test_fills_only_what_is_missing(self, bucket):
        seed(bucket, recorded_at="2026-04-12")

        applied = backfill_sidecar(
            bucket, KEY, {"recorded_at": "1999-01-01", "duration_s": 412.0}
        )

        assert applied == {"duration_s": 412.0}
        after = stored(bucket)
        assert after["recorded_at"] == "2026-04-12"
        assert after["duration_s"] == 412.0

    def test_writes_nothing_when_there_is_nothing_to_add(self, bucket):
        """A no-op run must not create an object version.

        B2 keeps every version unless a lifecycle rule says otherwise, so a
        sync that rewrote an unchanged sidecar on every run would quietly bill
        for it.
        """
        seed(bucket, duration_s=412.0)
        before = bucket.get(KEY)

        assert backfill_sidecar(bucket, KEY, {"duration_s": 999.0}) == {}
        assert bucket.get(KEY) == before

    def test_an_empty_string_counts_as_absent(self, bucket):
        seed(bucket, recorded_at="")

        assert backfill_sidecar(bucket, KEY, {"recorded_at": "2026-04-12"})
        assert stored(bucket)["recorded_at"] == "2026-04-12"

    def test_a_zero_duration_is_not_offered(self, bucket):
        """`None` means "nothing found"; it must not be written as a value."""
        seed(bucket)

        assert backfill_sidecar(bucket, KEY, {"duration_s": None}) == {}
        assert "duration_s" not in stored(bucket)


class TestFieldOrder:
    def test_known_fields_are_written_in_order(self, bucket):
        payload = canonical(
            {"thumbnail": "clip.mp4.jpg", "id": "x", "schema": 1, "file": "clip.mp4"}
        )
        assert list(payload) == ["schema", "id", "file", "thumbnail"]

    def test_unknown_fields_keep_their_order_at_the_end(self):
        payload = canonical({"zeta": 1, "id": "x", "alpha": 2, "schema": 1})
        assert list(payload) == ["schema", "id", "zeta", "alpha"]

    def test_agrees_with_what_adoption_emits(self):
        """Two writers, one field order.

        `adopt.sidecar_payload` builds its dict in a fixed sequence and this
        module reorders to FIELD_ORDER. If they disagreed, a sidecar written by
        `sync` and the same sidecar after one edit would diff on ordering
        alone.
        """
        emitted = sidecar_payload(
            filename="clip.mp4",
            new_id="x",
            uploaded_at="2026-05-01T00:00:00Z",
            size_bytes=1,
            media_type="video/mp4",
            thumbnail="clip.mp4.jpg",
            title="Recital",
            recorded_at="2026-04-12",
            duration_s=412.0,
            sha256="abc",
        )
        assert list(emitted) == [name for name in FIELD_ORDER if name in emitted]

    def test_a_merge_reorders_an_out_of_order_sidecar(self, bucket):
        bucket.seed(
            KEY,
            json.dumps(
                {"file": "clip.mp4", "schema": 1, "uploaded_at": "z", "id": "x"}
            ).encode(),
        )

        merge_sidecar(bucket, KEY, {"title": "Recital"})

        assert list(stored(bucket)) == [
            "schema",
            "id",
            "file",
            "title",
            "uploaded_at",
        ]


class TestReadAndMissing:
    def test_read_returns_the_fallback_when_the_key_is_gone(self, bucket):
        assert read_sidecar(bucket, KEY, fallback={"id": "x"}) == {"id": "x"}

    def test_missing_fields_matches_what_the_writers_skip(self):
        payload = {"duration_s": 412.0, "recorded_at": ""}
        assert missing_fields(payload, ("recorded_at", "duration_s", "title")) == (
            "recorded_at",
            "title",
        )
