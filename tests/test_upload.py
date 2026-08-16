"""Preflight, key derivation, and write order for `keepsake add`."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from keepsake.core import upload as upload_mod
from keepsake.core.upload import (
    PrefixError,
    dated_prefix,
    normalize_prefix,
    plan_uploads,
    upload_all,
    upload_one,
)
from keepsake.storage.base import Obj, MediaExists, MediaTooLarge, MediaWriteRefused
from keepsake.storage.local import LocalDirBucket

from test_moov import movie, mvhd_v0, seconds_since_1904

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class CaseSensitiveBucket:
    """Just enough bucket to preflight against, with object-storage semantics.

    Keys are case-sensitive here, as they are in B2 and S3 and as they are not
    on the macOS filesystem the rest of the suite runs on.
    """

    name = "remote"

    def __init__(self, keys: set[str]):
        self.keys = set(keys)

    def list(self, prefix: str = ""):
        return (
            Obj(key=key, size=1) for key in sorted(self.keys) if key.startswith(prefix)
        )

    def head(self, key: str):
        return Obj(key=key, size=1) if key in self.keys else None


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path / "bucket", name="test", readonly=False)


@pytest.fixture
def source(tmp_path):
    """A directory of local files to upload from."""
    directory = tmp_path / "source"
    directory.mkdir()
    return directory


def make_movie(directory, name: str, *, recorded=None, duration=600) -> "object":
    """A real (tiny) QuickTime file, header and all."""
    if recorded is not None and recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    stamp = seconds_since_1904(recorded) if recorded else 0
    path = directory / name
    path.write_bytes(movie(mvhd_v0(creation=stamp, duration=duration)).getvalue())
    return path


def ids():
    counter = iter(range(1, 100))
    return lambda: f"01HQ8XKPZR4M2N7QVWJT3YFB{next(counter):02d}"


class TestNormalizePrefix:
    def test_unset_means_the_dated_layout(self):
        assert normalize_prefix(None) is None
        assert normalize_prefix("") is None
        assert normalize_prefix("   ") is None

    def test_a_lone_slash_is_the_bucket_root(self):
        """The only way to ask for the root, so it is never an accident."""
        assert normalize_prefix("/") == ""

    def test_adds_exactly_one_trailing_slash(self):
        assert normalize_prefix("home-movies") == "home-movies/"
        assert normalize_prefix("home-movies/") == "home-movies/"
        assert normalize_prefix("/home-movies//") == "home-movies/"

    def test_keeps_nesting(self):
        assert normalize_prefix("a/b/c") == "a/b/c/"

    def test_rejects_relative_segments(self):
        with pytest.raises(PrefixError):
            normalize_prefix("../escape")


class TestDatedPrefix:
    def test_uses_the_recording_date(self):
        assert dated_prefix("2019-03-07", NOW) == "2019/03/"

    def test_falls_back_to_today(self):
        assert dated_prefix(None, NOW) == "2026/08/"

    def test_ignores_an_unparseable_date(self):
        assert dated_prefix("sometime in 1985", NOW) == "2026/08/"


class TestKeyDerivation:
    def test_files_by_the_recording_date_from_the_header(self, bucket, source):
        """A tape digitised today still lands in the year it was shot."""
        path = make_movie(source, "recital.mov", recorded=datetime(2019, 3, 7))
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert candidate.key == "2019/03/recital.mov"
        assert candidate.recorded_at == "2019-03-07"
        assert candidate.duration_s == 1.0

    def test_falls_back_to_today_without_a_header_date(self, bucket, source):
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert candidate.key == "2026/08/clip.mov"
        assert candidate.recorded_at is None

    def test_into_overrides_the_layout(self, bucket, source):
        path = make_movie(source, "clip.mov", recorded=datetime(2019, 3, 7))
        [candidate] = plan_uploads([path], bucket, into="home-movies", now=NOW)
        assert candidate.key == "home-movies/clip.mov"

    def test_into_slash_is_the_bucket_root(self, bucket, source):
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, into="/", now=NOW)
        assert candidate.key == "clip.mov"

    def test_as_name_renames(self, bucket, source):
        path = make_movie(source, "IMG_0002.MOV", recorded=datetime(2026, 5, 22))
        [candidate] = plan_uploads([path], bucket, as_name="recital.mov", now=NOW)
        assert candidate.key == "2026/05/recital.mov"

    def test_media_type_comes_from_the_extension(self, bucket, source):
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert candidate.media_type == "video/quicktime"


class TestPreflight:
    def test_missing_file(self, bucket, source):
        [candidate] = plan_uploads([source / "nope.mov"], bucket, now=NOW)
        assert not candidate.ok
        assert "no such file" in candidate.problem

    def test_directory_is_not_a_file(self, bucket, source):
        [candidate] = plan_uploads([source], bucket, now=NOW)
        assert "not a regular file" in candidate.problem

    def test_no_extension_is_refused(self, bucket, source):
        """SPEC requires an extension naming the format."""
        path = source / "recital"
        path.write_bytes(b"x" * 64)
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert "no file extension" in candidate.problem

    def test_dotfile_is_refused(self, bucket, source):
        path = source / ".hidden.mov"
        path.write_bytes(b"x" * 64)
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert "no file extension" in candidate.problem

    def test_over_the_ceiling_is_refused(self, bucket, source, monkeypatch):
        monkeypatch.setattr(upload_mod, "MAX_SINGLE_PUT", 64)
        path = make_movie(source, "big.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert not candidate.ok
        assert "single-upload limit" in candidate.problem

    def test_empty_file_is_refused(self, bucket, source):
        path = source / "empty.mov"
        path.write_bytes(b"")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert "empty file" in candidate.problem

    def test_existing_key_is_refused(self, bucket, source):
        bucket.seed("2026/08/clip.mov", b"already here")
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert "already exists" in candidate.problem

    def test_case_only_collision_is_refused(self, source):
        """SPEC: no filesystem the archive lands on can hold both.

        Needs `CaseSensitiveBucket` rather than the local one: macOS's
        filesystem is case-insensitive, so a LocalDirBucket seeded with
        `CLIP.mov` answers `head("clip.mov")` with a hit and the plainer
        "already exists" check fires first. Object storage keeps both keys,
        which is precisely why this check has to exist at all.
        """
        remote = CaseSensitiveBucket({"2026/08/CLIP.mov"})
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], remote, now=NOW)
        assert "only in case" in candidate.problem

    def test_companion_shaped_key_is_refused(self, bucket, source):
        """`piano.mp4.jpg` would be read as a thumbnail, never as media."""
        bucket.seed("2026/08/piano.mp4", b"video")
        path = make_movie(source, "piano.mp4.jpg")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        assert "companion key" in candidate.problem

    def test_two_files_in_one_batch_claiming_one_key(self, bucket, source):
        """Two phones both emitting IMG_0002.MOV is not hypothetical."""
        one = make_movie(source, "IMG_0002.MOV")
        nested = source / "other"
        nested.mkdir()
        two = make_movie(nested, "IMG_0002.MOV")

        first, second = plan_uploads([one, two], bucket, now=NOW)
        assert first.ok
        assert "already claims" in second.problem

    def test_one_bad_file_does_not_sink_the_batch(self, bucket, source):
        good = make_movie(source, "good.mov")
        bad = source / "bad"
        bad.write_bytes(b"x" * 64)
        candidates = plan_uploads([good, bad], bucket, now=NOW)
        assert [c.ok for c in candidates] == [True, False]


class TestUpload:
    def test_writes_media_then_sidecar(self, bucket, source):
        path = make_movie(source, "recital.mov", recorded=datetime(2026, 5, 22))
        [candidate] = plan_uploads([path], bucket, now=NOW)

        key = upload_one(bucket, candidate, new_id=ids(), title="Spring Recital", now=NOW)

        assert key == "2026/05/recital.mov"
        assert bucket.get(key) == path.read_bytes()

        sidecar = json.loads(bucket.get("2026/05/recital.mov.json"))
        assert sidecar["file"] == "recital.mov"
        assert sidecar["title"] == "Spring Recital"
        assert sidecar["recorded_at"] == "2026-05-22"
        assert sidecar["duration_s"] == 1.0
        assert sidecar["media_type"] == "video/quicktime"
        assert sidecar["uploaded_at"] == "2026-08-15T12:00:00Z"
        assert sidecar["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert sidecar["size_bytes"] == path.stat().st_size

    def test_sidecar_is_written_last(self, bucket, source):
        """The commit marker cannot precede the thing it commits."""
        order: list[str] = []
        original_media, original_put = bucket.put_media, bucket.put
        bucket.put_media = lambda *a, **k: (order.append("media"), original_media(*a, **k))[1]
        bucket.put = lambda *a, **k: (order.append("sidecar"), original_put(*a, **k))[1]

        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        upload_one(bucket, candidate, new_id=ids(), now=NOW)

        assert order == ["media", "sidecar"]

    def test_absent_title_is_omitted_not_null(self, bucket, source):
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        upload_one(bucket, candidate, new_id=ids(), now=NOW)
        assert "title" not in json.loads(bucket.get("2026/08/clip.mov.json"))

    def test_reports_progress(self, bucket, source):
        path = make_movie(source, "clip.mov")
        [candidate] = plan_uploads([path], bucket, now=NOW)
        seen: list[int] = []
        upload_one(bucket, candidate, new_id=ids(), progress=seen.append, now=NOW)
        assert seen and seen[-1] == candidate.size

    def test_upload_all_skips_refused_files(self, bucket, source):
        good = make_movie(source, "good.mov")
        bad = source / "bad"
        bad.write_bytes(b"x" * 64)

        written, failures = upload_all(
            bucket, plan_uploads([good, bad], bucket, now=NOW), new_id=ids()
        )

        assert written == ["2026/08/good.mov"]
        assert failures == []
        assert bucket.head("bad") is None


class TestGuard:
    """The backstop, for callers that skipped preflight."""

    def test_refuses_to_overwrite_existing_media(self, bucket, source):
        bucket.seed("2026/08/clip.mov", b"already here")
        path = make_movie(source, "clip.mov")
        with path.open("rb") as fh, pytest.raises(MediaExists):
            bucket.put_media("2026/08/clip.mov", fh, size=path.stat().st_size)

    def test_refuses_a_companion_shaped_key(self, bucket, source):
        path = make_movie(source, "clip.mov")
        with path.open("rb") as fh, pytest.raises(MediaWriteRefused):
            bucket.put_media("2026/08/piano.mp4.json", fh, size=path.stat().st_size)

    def test_refuses_a_key_with_no_extension(self, bucket, source):
        path = make_movie(source, "clip.mov")
        with path.open("rb") as fh, pytest.raises(MediaWriteRefused):
            bucket.put_media("2026/08/clip", fh, size=path.stat().st_size)

    def test_refuses_over_the_ceiling(self, bucket, source):
        path = make_movie(source, "clip.mov")
        with path.open("rb") as fh, pytest.raises(MediaTooLarge):
            bucket.put_media("2026/08/clip.mov", fh, size=6 * 1024**3)

    def test_refuses_on_a_readonly_bucket(self, tmp_path, source):
        readonly = LocalDirBucket(tmp_path / "ro", name="test", readonly=True)
        path = make_movie(source, "clip.mov")
        with path.open("rb") as fh, pytest.raises(Exception):
            readonly.put_media("2026/08/clip.mov", fh, size=path.stat().st_size)
