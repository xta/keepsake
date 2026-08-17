"""Rendering a still for a video and filing it as that video's thumbnail.

Two halves. The planning tests run anywhere and are about SPEC.md's naming
rules -- what counts as needing a thumbnail, and what the thumbnail is called.
The rendering tests shell out to the real ffmpeg against real (tiny, generated)
videos, because the interesting failures here are ffmpeg's: a clip shorter than
the seek point, a file that is not video at all. A stubbed ffmpeg would assert
only that we can write a mock.

`LocalDirBucket.presigned_url` hands back a `file://` URI, which ffmpeg reads
the same way it reads a presigned B2 URL, so the whole pass exercises end to
end with no network and no credentials.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from keepsake.core import thumbs
from keepsake.core.classify import classify
from keepsake.storage.local import LocalDirBucket

needs_ffmpeg = pytest.mark.skipif(
    not thumbs.ffmpeg_available(), reason="ffmpeg and ffprobe are not on PATH"
)


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


@pytest.fixture(scope="session")
def videos(tmp_path_factory):
    """A 12-second 1920x1080 clip and a 3-second 640x480 one.

    The short one is the interesting fixture: the default seek is 5 seconds,
    so it is the case where ffmpeg finds no frame and the fallback has to save
    the render. Phone libraries are full of three-second clips.
    """
    if not thumbs.ffmpeg_available():
        pytest.skip("ffmpeg is not on PATH")

    directory = tmp_path_factory.mktemp("videos")
    made = {}
    for name, size, seconds in (("long", "1920x1080", 12), ("short", "640x480", 3)):
        path = directory / f"{name}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y",
                "-f", "lavfi",
                "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        made[name] = path.read_bytes()
    return made


def seed_sidecar(bucket, media_key, **extra):
    bucket.seed(
        media_key + ".json",
        json.dumps(
            {
                "schema": 1,
                "id": "01a0098c-ebfd-7e9f-bac0-ca39f3495b09",
                "file": media_key.rsplit("/", 1)[-1],
                "uploaded_at": "2026-05-01T00:00:00Z",
                **extra,
            }
        ).encode(),
    )


def plan_for(bucket):
    return thumbs.plan(bucket, classify(bucket.list()))


class TestThumbKey:
    def test_appends_to_the_complete_filename(self):
        assert thumbs.thumb_key_for("2026/piano.mp4") == "2026/piano.mp4.jpg"

    def test_doubles_the_extension_on_an_image(self):
        """SPEC.md: `img3.jpg.jpg` looks like a mistake and is not one."""
        assert thumbs.thumb_key_for("img3.jpg") == "img3.jpg.jpg"


class TestPlan:
    def test_includes_a_video_with_no_thumbnail(self, bucket):
        bucket.seed("2026/clip.mp4", b"x")
        seed_sidecar(bucket, "2026/clip.mp4")

        plan, failures = plan_for(bucket)

        assert failures == []
        assert [t.media_key for t in plan] == ["2026/clip.mp4"]
        assert plan[0].thumb_key == "2026/clip.mp4.jpg"
        assert plan[0].sidecar_key == "2026/clip.mp4.json"

    def test_skips_a_video_that_already_has_one(self, bucket):
        bucket.seed("2026/clip.mp4", b"x")
        seed_sidecar(bucket, "2026/clip.mp4")
        bucket.seed("2026/clip.mp4.jpg", b"thumb")

        plan, _ = plan_for(bucket)

        assert plan == []

    def test_a_thumbnail_in_another_format_still_counts(self, bucket):
        """SPEC.md allows .jpg, .png or .webp. Rendering a second one would
        make the library ambiguous."""
        bucket.seed("2026/clip.mp4", b"x")
        seed_sidecar(bucket, "2026/clip.mp4")
        bucket.seed("2026/clip.mp4.webp", b"thumb")

        plan, _ = plan_for(bucket)

        assert plan == []

    def test_includes_media_with_no_sidecar_yet(self, bucket):
        """The image is worth writing regardless: classification recognises a
        thumbnail before its media has a sidecar, so adoption picks the field
        up on its own."""
        bucket.seed("2026/clip.mp4", b"x")

        plan, _ = plan_for(bucket)

        assert [t.media_key for t in plan] == ["2026/clip.mp4"]
        assert plan[0].sidecar_key is None

    def test_skips_images_and_audio(self, bucket):
        for key in ("2026/snap.jpg", "2026/voice.m4a", "notes.txt"):
            bucket.seed(key, b"x")

        plan, _ = plan_for(bucket)

        assert plan == []

    def test_skips_media_whose_thumbnails_are_ambiguous(self, bucket):
        """Two thumbnails already claim this file, so classification refuses to
        pick one and reports the ambiguity instead. Rendering a third candidate
        into that is exactly the choosing SPEC.md says not to do -- and it is
        the tempting bug, since `result.thumbnails` holds no entry for this key
        and it therefore looks like a file with no thumbnail at all.
        """
        bucket.seed("2026/clip.mp4", b"x")
        bucket.seed("2026/clip.mp4.jpg", b"thumb")
        bucket.seed("2026/clip.mp4.png", b"thumb")

        result = classify(bucket.list())
        assert "2026/clip.mp4" not in result.thumbnails
        assert "2026/clip.mp4" in result.ambiguous

        plan, _ = thumbs.plan(bucket, result)

        assert plan == []

    def test_notes_when_the_sidecar_still_wants_a_duration(self, bucket):
        bucket.seed("2026/clip.mp4", b"x")
        seed_sidecar(bucket, "2026/clip.mp4")

        plan, _ = plan_for(bucket)

        assert plan[0].needs_duration is True

    def test_does_not_ask_for_a_duration_already_recorded(self, bucket):
        bucket.seed("2026/clip.mp4", b"x")
        seed_sidecar(bucket, "2026/clip.mp4", duration_s=412.0)

        plan, _ = plan_for(bucket)

        assert plan[0].needs_duration is False

    def test_an_unreadable_sidecar_is_reported(self, bucket):
        bucket.seed("2026/clip.mp4", b"x")
        bucket.seed("2026/clip.mp4.json", b"{ broken")

        plan, failures = plan_for(bucket)

        assert plan == []
        assert [key for key, _ in failures] == ["2026/clip.mp4.json"]


@needs_ffmpeg
class TestRender:
    def test_writes_a_jpeg(self, tmp_path, videos):
        source = tmp_path / "long.mp4"
        source.write_bytes(videos["long"])
        dest = tmp_path / "out.jpg"

        thumbs.render(source.as_uri(), dest)

        assert dest.is_file()
        assert dest.read_bytes()[:2] == b"\xff\xd8"  # JPEG SOI

    def test_scales_down_and_keeps_the_aspect_ratio(self, tmp_path, videos):
        source = tmp_path / "long.mp4"
        source.write_bytes(videos["long"])
        dest = tmp_path / "out.jpg"

        thumbs.render(source.as_uri(), dest, width=640)

        assert _dimensions(dest) == (640, 360)

    def test_never_upscales(self, tmp_path, videos):
        """A 640-wide clip stays 640 wide rather than being blown up and
        stored bigger than the frame it came from."""
        source = tmp_path / "short.mp4"
        source.write_bytes(videos["short"])
        dest = tmp_path / "out.jpg"

        thumbs.render(source.as_uri(), dest, width=1280)

        assert _dimensions(dest) == (640, 480)

    def test_a_clip_shorter_than_the_seek_falls_back_to_the_first_frame(
        self, tmp_path, videos
    ):
        source = tmp_path / "short.mp4"  # three seconds
        source.write_bytes(videos["short"])
        dest = tmp_path / "out.jpg"

        thumbs.render(source.as_uri(), dest, seek=5.0)

        assert dest.is_file() and dest.stat().st_size > 0

    def test_a_file_that_is_not_video_raises(self, tmp_path):
        source = tmp_path / "notes.mp4"
        source.write_bytes(b"this is not a video")

        with pytest.raises(thumbs.ThumbnailFailed):
            thumbs.render(source.as_uri(), tmp_path / "out.jpg")


@needs_ffmpeg
class TestProbeDuration:
    def test_reads_the_runtime(self, tmp_path, videos):
        source = tmp_path / "long.mp4"
        source.write_bytes(videos["long"])

        assert thumbs.probe_duration(source.as_uri()) == pytest.approx(12.0, abs=0.2)

    def test_none_rather_than_raising_on_a_file_it_cannot_read(self, tmp_path):
        source = tmp_path / "notes.mp4"
        source.write_bytes(b"not a video")

        assert thumbs.probe_duration(source.as_uri()) is None


@needs_ffmpeg
class TestApply:
    def test_uploads_the_image_and_records_it_in_the_sidecar(self, bucket, videos):
        bucket.seed("2026/clip.mp4", videos["long"])
        seed_sidecar(bucket, "2026/clip.mp4")

        plan, _ = plan_for(bucket)
        written, failures = thumbs.apply(bucket, plan)

        assert (written, failures) == (1, [])
        assert bucket.get("2026/clip.mp4.jpg")[:2] == b"\xff\xd8"
        stored = json.loads(bucket.get("2026/clip.mp4.json"))
        # SPEC.md: filename relative to the sidecar's own directory, not the key.
        assert stored["thumbnail"] == "clip.mp4.jpg"

    def test_fills_the_duration_on_the_way_past(self, bucket, videos):
        bucket.seed("2026/clip.mp4", videos["long"])
        seed_sidecar(bucket, "2026/clip.mp4")

        thumbs.apply(bucket, plan_for(bucket)[0])

        stored = json.loads(bucket.get("2026/clip.mp4.json"))
        assert stored["duration_s"] == pytest.approx(12.0, abs=0.2)

    def test_leaves_a_duration_already_recorded(self, bucket, videos):
        bucket.seed("2026/clip.mp4", videos["long"])
        seed_sidecar(bucket, "2026/clip.mp4", duration_s=99.0)

        thumbs.apply(bucket, plan_for(bucket)[0])

        assert json.loads(bucket.get("2026/clip.mp4.json"))["duration_s"] == 99.0

    def test_media_with_no_sidecar_gets_an_image_and_nothing_else(
        self, bucket, videos
    ):
        bucket.seed("2026/clip.mp4", videos["long"])

        written, failures = thumbs.apply(bucket, plan_for(bucket)[0])

        assert (written, failures) == (1, [])
        assert bucket.head("2026/clip.mp4.jpg") is not None
        assert bucket.head("2026/clip.mp4.json") is None

    def test_one_bad_file_does_not_stop_the_others(self, bucket, videos):
        """Each thumbnail is independent and entirely derived, so a partial
        pass is a safe state."""
        bucket.seed("2026/broken.mp4", b"not a video")
        bucket.seed("2026/clip.mp4", videos["long"])

        written, failures = thumbs.apply(bucket, plan_for(bucket)[0])

        assert written == 1
        assert [key for key, _ in failures] == ["2026/broken.mp4"]
        assert bucket.head("2026/clip.mp4.jpg") is not None
        assert bucket.head("2026/broken.mp4.jpg") is None

    def test_a_second_run_has_nothing_to_do(self, bucket, videos):
        bucket.seed("2026/clip.mp4", videos["long"])
        seed_sidecar(bucket, "2026/clip.mp4")
        thumbs.apply(bucket, plan_for(bucket)[0])

        assert plan_for(bucket)[0] == []

    def test_announces_each_file_before_rendering_it(self, bucket, videos):
        bucket.seed("2026/clip.mp4", videos["long"])
        seen = []

        thumbs.apply(
            bucket,
            plan_for(bucket)[0],
            on_start=lambda thumb, at, total: seen.append((thumb.media_key, at, total)),
        )

        assert seen == [("2026/clip.mp4", 1, 1)]

    def test_a_read_only_bucket_is_refused(self, tmp_path, videos):
        writable = LocalDirBucket(tmp_path, readonly=False)
        writable.seed("2026/clip.mp4", videos["long"])
        readonly = LocalDirBucket(tmp_path, readonly=True)

        written, failures = thumbs.apply(readonly, plan_for(writable)[0])

        assert written == 0
        assert "ReadOnlyBucket" in failures[0][1]


def _dimensions(path) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    width, height = out.split(",")[:2]
    return int(width), int(height)
