from __future__ import annotations

import json

import pytest

from keepsake.core.check import check
from keepsake.core.classify import classify
from keepsake.core.index import build_index
from keepsake.storage.base import MediaWriteRefused, ReadOnlyBucket, is_writable_key
from keepsake.storage.local import LocalDirBucket


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


def sidecar_bytes(file: str, **extra) -> bytes:
    payload = {
        "schema": 1,
        "id": "01HQ8XKPZR4M2N7QVWJT3YFBCD",
        "file": file,
        "uploaded_at": "2026-04-14T02:11:09Z",
        **extra,
    }
    return json.dumps(payload).encode()


def test_companions_are_matched_by_full_filename(bucket):
    bucket.seed("media/2026/piano.mp4", b"video")
    bucket.seed("media/2026/piano.mp4.json", sidecar_bytes("piano.mp4"))
    bucket.seed("media/2026/piano.mp4.jpg", b"thumb")

    result = classify(bucket.list())

    assert result.media == {"media/2026/piano.mp4": "media/2026/piano.mp4.json"}
    assert result.thumbnails == {"media/2026/piano.mp4": "media/2026/piano.mp4.jpg"}
    assert result.unindexed == []
    assert result.orphan_sidecars == []


def test_same_stem_different_extensions_coexist(bucket):
    bucket.seed("vacation.mp4", b"a")
    bucket.seed("vacation.mp4.json", sidecar_bytes("vacation.mp4"))
    bucket.seed("vacation.mov", b"b")
    bucket.seed("vacation.mov.json", sidecar_bytes("vacation.mov"))

    result = classify(bucket.list())

    assert set(result.media) == {"vacation.mp4", "vacation.mov"}


def test_root_index_is_reserved_but_nested_index_is_a_sidecar(bucket):
    """A nested index.json is an ordinary sidecar, never the reserved key.

    It can only ever be an orphan one: it claims a media key of `index`, and
    SPEC's extension rule means a file named `index` cannot be media.
    """
    bucket.seed("index.json", b"{}")
    bucket.seed("media/index", b"a file literally named index")
    bucket.seed("media/index.json", sidecar_bytes("index"))

    result = classify(bucket.list())

    assert result.index_present is True
    assert result.media == {}
    assert result.orphan_sidecars == ["media/index.json"]
    assert result.ignored == ["media/index"]


def test_media_without_sidecar_is_unindexed_not_hidden(bucket):
    bucket.seed("IMG_4471.mov", b"video")

    result = classify(bucket.list())

    assert result.unindexed == ["IMG_4471.mov"]
    assert result.media == {}


def test_sidecar_without_media_is_reported(bucket):
    bucket.seed("gone.mp4.json", sidecar_bytes("gone.mp4"))

    result = classify(bucket.list())

    assert result.orphan_sidecars == ["gone.mp4.json"]
    assert result.media == {}
    codes = {f.code for f in check(result, bucket)}
    assert "sidecar-no-media" in codes


def test_standalone_image_is_media_when_no_sidecar_claims_it(bucket):
    bucket.seed("sunset.jpg", b"image")

    result = classify(bucket.list())

    assert result.unindexed == ["sunset.jpg"]
    assert result.thumbnails == {}


def test_thumbnail_is_recognised_before_its_media_has_a_sidecar(bucket):
    """SPEC: classification describes what a key is, not whether it is complete.

    A bucket freshly filled by an upload tool must not count derived files as
    library items, so the thumbnail resolves before anything is adopted.
    """
    bucket.seed("clip.mp4", b"video")
    bucket.seed("clip.mp4.jpg", b"thumb")

    result = classify(bucket.list())

    assert result.thumbnails == {"clip.mp4": "clip.mp4.jpg"}
    assert result.unindexed == ["clip.mp4"]


def test_thumbnail_of_an_image_doubles_the_extension(bucket):
    bucket.seed("img3.jpg", b"photo")
    bucket.seed("img3.jpg.jpg", b"thumb")

    result = classify(bucket.list())

    assert result.thumbnails == {"img3.jpg": "img3.jpg.jpg"}
    assert result.unindexed == ["img3.jpg"]


def test_dotfiles_are_not_media(bucket):
    """B2 writes .bzEmpty into every folder made in its web UI."""
    bucket.seed("2026/05/.bzEmpty", b"")
    bucket.seed("2026/05/clip.mp4", b"video")

    result = classify(bucket.list())

    assert result.unindexed == ["2026/05/clip.mp4"]
    assert result.ignored == ["2026/05/.bzEmpty"]
    assert "not-media" in {f.code for f in check(result, bucket)}


def test_extensionless_keys_are_not_catalogued(bucket):
    bucket.seed("README", b"notes")

    result = classify(bucket.list())

    assert result.unindexed == []
    assert result.ignored == ["README"]


def test_keys_differing_only_in_case_are_an_error():
    """LocalDirBucket cannot hold both on macOS, which is the whole point."""
    from keepsake.storage.base import Obj

    result = classify([Obj(key="IMG.mov", size=1), Obj(key="img.mov", size=1)])

    assert result.case_collisions == {"img.mov": ["IMG.mov", "img.mov"]}
    findings = {f.code: f for f in check(result)}
    assert findings["case-collision"].level == "error"


def test_index_inlines_sidecars_sorted_by_path(bucket):
    bucket.seed("b.mp4", b"")
    bucket.seed("b.mp4.json", sidecar_bytes("b.mp4", title="Bee"))
    bucket.seed("a.mp4", b"")
    bucket.seed("a.mp4.json", sidecar_bytes("a.mp4", title="Ay"))

    index = build_index(classify(bucket.list()), bucket, generated_at="2026-07-22T18:03:11Z")

    assert index["count"] == 2
    assert [item["path"] for item in index["items"]] == ["a.mp4", "b.mp4"]
    assert index["items"][0]["title"] == "Ay"


def test_check_flags_advisory_file_field_mismatch(bucket):
    bucket.seed("real.mp4", b"")
    bucket.seed("real.mp4.json", sidecar_bytes("wrong.mp4"))

    findings = {f.code for f in check(classify(bucket.list()), bucket)}

    assert "sidecar-file-mismatch" in findings


class TestMediaGuard:
    def test_media_writes_are_refused(self, bucket):
        with pytest.raises(MediaWriteRefused):
            bucket.put("holiday.mp4", b"nope")

    def test_media_deletes_are_refused(self, bucket):
        bucket.seed("holiday.mp4", b"precious")
        with pytest.raises(MediaWriteRefused):
            bucket.delete("holiday.mp4")
        assert bucket.head("holiday.mp4") is not None

    def test_companions_are_writable(self, bucket):
        bucket.put("holiday.mp4.json", b"{}")
        bucket.put("holiday.mp4.jpg", b"thumb")
        bucket.put("index.json", b"{}")

    def test_explicit_override_reaches_media(self, bucket):
        bucket.seed("holiday.mp4", b"precious")
        bucket.delete("holiday.mp4", allow_media=True)
        assert bucket.head("holiday.mp4") is None

    def test_readonly_bucket_refuses_even_companions(self, tmp_path):
        ro = LocalDirBucket(tmp_path, readonly=True)
        with pytest.raises(ReadOnlyBucket):
            ro.put("x.mp4.json", b"{}")


@pytest.mark.parametrize(
    "key,writable",
    [
        ("index.json", True),
        ("piano.mp4.json", True),
        ("piano.mp4.jpg", True),
        ("media/2026/piano.mp4.webp", True),
        ("piano.mp4", False),
        ("sunset.jpg", False),  # no inner extension -> standalone media
        ("holiday.mov", False),
        ("notes.txt", False),
    ],
)
def test_is_writable_key(key, writable):
    assert is_writable_key(key) is writable
