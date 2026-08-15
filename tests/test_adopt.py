from __future__ import annotations

import json
from itertools import count

import pytest

from keepsake.core import adopt as adopt_mod
from keepsake.core import index as index_mod
from keepsake.core.check import check
from keepsake.core.classify import classify
from keepsake.storage.base import ReadOnlyBucket
from keepsake.storage.local import LocalDirBucket


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


@pytest.fixture
def ids():
    counter = count(1)
    return lambda: f"01HQ8XKPZR4M2N7QVWJT3YFB{next(counter):02d}"


def test_plan_covers_every_unindexed_media_file(bucket, ids):
    bucket.seed("2026/05/IMG_0002.MOV", b"x" * 100)
    bucket.seed("2026/05/IMG_0007.MOV", b"y" * 200)

    stubs = adopt_mod.plan(classify(bucket.list()), new_id=ids)

    assert [s.media_key for s in stubs] == ["2026/05/IMG_0002.MOV", "2026/05/IMG_0007.MOV"]
    assert [s.sidecar_key for s in stubs] == [
        "2026/05/IMG_0002.MOV.json",
        "2026/05/IMG_0007.MOV.json",
    ]


def test_stub_records_only_what_is_known(bucket, ids):
    bucket.seed("2026/05/IMG_0002.MOV", b"x" * 100)

    payload = adopt_mod.plan(classify(bucket.list()), new_id=ids)[0].payload

    assert payload["schema"] == 1
    assert payload["file"] == "IMG_0002.MOV"
    assert payload["size_bytes"] == 100
    assert payload["media_type"] == "video/quicktime"
    assert payload["uploaded_at"].endswith("Z")
    # Nothing guessed from the filename or the path.
    assert "title" not in payload
    assert "recorded_at" not in payload


def test_sidecar_suffix_is_lowercase_even_for_uppercase_media(bucket, ids):
    bucket.seed("CLIP.MOV", b"x")
    assert adopt_mod.plan(classify(bucket.list()), new_id=ids)[0].sidecar_key == "CLIP.MOV.json"


def test_existing_sidecars_are_left_alone(bucket, ids):
    bucket.seed("a.mp4", b"x")
    bucket.seed("a.mp4.json", json.dumps({"schema": 1, "id": "x", "file": "a.mp4", "uploaded_at": "z"}).encode())
    bucket.seed("b.mp4", b"y")

    stubs = adopt_mod.plan(classify(bucket.list()), new_id=ids)

    assert [s.media_key for s in stubs] == ["b.mp4"]


def test_probable_thumbnails_are_not_adopted_as_media(bucket, ids):
    """`clip.mp4.jpg` is derived; adopting it would enshrine it as a library item."""
    bucket.seed("clip.mp4", b"x")
    bucket.seed("clip.mp4.jpg", b"thumb")

    stubs = adopt_mod.plan(classify(bucket.list()), new_id=ids)

    assert [s.media_key for s in stubs] == ["clip.mp4"]


def test_apply_writes_sidecars_and_the_library_becomes_indexed(bucket, ids):
    bucket.seed("2026/05/IMG_0002.MOV", b"x" * 100)
    stubs = adopt_mod.plan(classify(bucket.list()), new_id=ids)

    assert adopt_mod.apply(bucket, stubs) == 1

    after = classify(bucket.list())
    assert after.media == {"2026/05/IMG_0002.MOV": "2026/05/IMG_0002.MOV.json"}
    assert after.unindexed == []
    assert not [f for f in check(after, bucket) if f.level == "error"]


def test_adopting_then_reindexing_produces_a_catalog(bucket, ids):
    bucket.seed("2026/05/IMG_0002.MOV", b"x" * 100)
    adopt_mod.apply(bucket, adopt_mod.plan(classify(bucket.list()), new_id=ids))

    result = classify(bucket.list())
    index_mod.write(bucket, index_mod.build_index(result, bucket))

    catalog = json.loads(bucket.get("index.json"))
    assert catalog["count"] == 1
    assert catalog["items"][0]["path"] == "2026/05/IMG_0002.MOV"
    # The index is reserved and must not be catalogued as a library item.
    assert classify(bucket.list()).index_present is True
    assert classify(bucket.list()).unindexed == []


def test_apply_is_refused_on_a_readonly_bucket(tmp_path, ids):
    writable = LocalDirBucket(tmp_path, readonly=False)
    writable.seed("a.mp4", b"x")
    stubs = adopt_mod.plan(classify(writable.list()), new_id=ids)

    readonly = LocalDirBucket(tmp_path, readonly=True)
    with pytest.raises(ReadOnlyBucket):
        adopt_mod.apply(readonly, stubs)


@pytest.mark.parametrize(
    "key,expected",
    [
        ("a.MOV", "video/quicktime"),
        ("a.mp4", "video/mp4"),
        ("a.HEIC", "image/heic"),
        ("a.mts", "video/mp2t"),
        ("noextension", None),
    ],
)
def test_media_type_guessing(key, expected):
    assert adopt_mod.guess_media_type(key) == expected
