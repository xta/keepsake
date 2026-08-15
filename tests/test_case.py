"""SPEC.md: companion suffixes match case-insensitively, media keys exactly."""

from __future__ import annotations

import json

import pytest

from keepsake.core.check import check
from keepsake.core.classify import classify
from keepsake.storage.base import Obj, split_companion
from keepsake.storage.local import LocalDirBucket


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


def sidecar(file: str) -> bytes:
    return json.dumps(
        {"schema": 1, "id": "01HQ8XKPZR4M2N7QVWJT3YFBCD", "file": file, "uploaded_at": "z"}
    ).encode()


@pytest.mark.parametrize(
    "key,expected",
    [
        ("IMG_0002.MOV.json", ("IMG_0002.MOV", "sidecar")),
        ("IMG_0002.MOV.JSON", ("IMG_0002.MOV", "sidecar")),
        ("IMG_0002.MOV.Json", ("IMG_0002.MOV", "sidecar")),
        ("IMG_0002.MOV.JPG", ("IMG_0002.MOV", "thumbnail")),
        ("IMG_0002.MOV.WebP", ("IMG_0002.MOV", "thumbnail")),
        ("IMG_0002.MOV", None),
        ("sunset.JPG", None),  # no inner extension -> standalone media
    ],
)
def test_split_companion_ignores_suffix_case(key, expected):
    assert split_companion(key) == expected


def test_uppercase_companions_are_recognised(bucket):
    bucket.seed("2026/05/IMG_0002.MOV", b"video")
    bucket.seed("2026/05/IMG_0002.MOV.JSON", sidecar("IMG_0002.MOV"))
    bucket.seed("2026/05/IMG_0002.MOV.JPG", b"thumb")

    result = classify(bucket.list())

    assert result.media == {"2026/05/IMG_0002.MOV": "2026/05/IMG_0002.MOV.JSON"}
    assert result.thumbnails == {"2026/05/IMG_0002.MOV": "2026/05/IMG_0002.MOV.JPG"}
    assert result.unindexed == []


def test_media_key_case_still_matters(bucket):
    """`clip.mov` and `clip.MOV` are different objects; companions do not cross."""
    bucket.seed("clip.MOV", b"video")
    bucket.seed("clip.mov.json", sidecar("clip.mov"))

    result = classify(bucket.list())

    assert result.media == {}
    assert result.unindexed == ["clip.MOV"]
    assert result.orphan_sidecars == ["clip.mov.json"]


def test_companions_differing_only_in_suffix_case_are_ambiguous():
    """Built from objects rather than files: macOS is case-insensitive, so
    `clip.MOV.json` and `clip.MOV.JSON` cannot coexist in a real directory.
    Object storage keys are case-sensitive, so a bucket can hold both."""
    result = classify(
        [
            Obj("clip.MOV", 5),
            Obj("clip.MOV.json", 10),
            Obj("clip.MOV.JSON", 10),
        ]
    )

    assert result.ambiguous == {"clip.MOV": ["clip.MOV.JSON", "clip.MOV.json"]}
    assert result.media == {}

    findings = {f.code for f in check(result, None, read_sidecars=False)}
    assert "ambiguous-companion" in findings


def test_two_thumbnails_for_one_media_file_are_ambiguous(bucket):
    bucket.seed("clip.MOV", b"video")
    bucket.seed("clip.MOV.json", sidecar("clip.MOV"))
    bucket.seed("clip.MOV.jpg", b"a")
    bucket.seed("clip.MOV.png", b"b")

    result = classify(bucket.list())

    assert result.thumbnails == {}
    assert result.ambiguous["clip.MOV"] == ["clip.MOV.jpg", "clip.MOV.png"]
