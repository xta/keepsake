"""Render a still for each video and upload it as that file's thumbnail.

SPEC.md calls thumbnails derived, optional and regenerable, and this pass is
what derives them: `{media}.jpg` beside the media, then the sidecar's
`thumbnail` field so a client reading `index.json` does not have to probe for
one. That ordering is SPEC.md's write order -- image first, sidecar after --
which means an interrupted run leaves an image nobody references rather than a
reference to an image that is not there. The next run picks it up.

ffmpeg reads a presigned URL directly, and B2 serves range requests, so
generating a thumbnail from a four-gigabyte video transfers a few megabytes
rather than the file. Nothing is downloaded whole and nothing is transcoded.

This is the expensive pass -- a decode per file, against a remote object, with
a dependency that has to be installed -- so it is gated behind `sync --thumbs`
rather than running with the ordinary metadata work. Media that already has a
thumbnail is skipped, so a rerun costs one listing.

Runtime comes nearly free while we are here: the decoder reads the header
either way. `core/backfill.py` gets `duration_s` more cheaply out of `mvhd` and
runs first, so ffprobe is only asked about files it could not read -- AVI, MKV,
WMV, the formats digitised home movies actually arrive in.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from keepsake.core.classify import Classification
from keepsake.core.sidecar import (
    SidecarUnreadable,
    merge_sidecar,
    missing_fields,
    read_sidecar,
)
from keepsake.core.survey import VIDEO_EXTS, extension_of
from keepsake.storage.base import Bucket

#: Where in the video to grab the frame. The first seconds of home video are
#: reliably a lens cap, a floor, or someone still pressing the button.
DEFAULT_SEEK = 5.0

#: Widest the image is written. A grid of these is the whole point, and a 4K
#: still is fifteen times the bytes for no visible gain in a grid cell. Never
#: upscales -- a 320-wide clip stays 320 wide.
DEFAULT_WIDTH = 640

#: ffmpeg's JPEG quality scale runs 2 (best) to 31. 3 is visually clean at
#: this size and small enough that a library of them is not worth thinking
#: about.
JPEG_QUALITY = 3

#: SPEC.md: writers emit lowercase suffixes.
THUMB_EXT = ".jpg"
THUMB_TYPE = "image/jpeg"

#: A remote decode that has not finished by now is stuck, not slow.
DEFAULT_TIMEOUT = 300


class FfmpegMissing(Exception):
    """ffmpeg or ffprobe is not on PATH."""


class ThumbnailFailed(Exception):
    """ffmpeg ran and produced nothing usable."""


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def require_ffmpeg() -> None:
    if not ffmpeg_available():
        raise FfmpegMissing(
            "ffmpeg and ffprobe are not on PATH. Thumbnails are rendered with "
            "them; install with `brew install ffmpeg`."
        )


@dataclass
class Thumb:
    """One thumbnail that would be generated."""

    media_key: str
    thumb_key: str
    #: None when the media has no sidecar yet. The image is still worth
    #: writing: classification recognises a thumbnail before its media has a
    #: sidecar, so the adoption pass picks the field up on its own.
    sidecar_key: str | None = None
    #: Whether that sidecar still wants `duration_s`, which decides if ffprobe
    #: is worth running at all.
    needs_duration: bool = False


def thumb_key_for(media_key: str) -> str:
    """SPEC.md: append the image extension to the *complete* filename.

    So `piano.mp4` gets `piano.mp4.jpg`, and the doubled extension on an image
    is deliberate rather than a bug.
    """
    return media_key + THUMB_EXT


def plan(
    bucket: Bucket,
    result: Classification,
    *,
    exts: set[str] = VIDEO_EXTS,
    want_duration: bool = True,
) -> tuple[list[Thumb], list[tuple[str, str]]]:
    """Which media still needs a thumbnail, and anything unreadable.

    Video only, by default. Images can carry thumbnails under SPEC.md and the
    doubled extension is well defined, but a phone library is mostly HEIC,
    which ffmpeg does not reliably decode, and an image already renders in a
    grid on its own. Widening `exts` is the way in if that changes.

    Media whose companions are ambiguous is skipped: SPEC.md says report the
    ambiguity rather than choosing, and writing a third candidate into it would
    be choosing.
    """
    thumbs: list[Thumb] = []
    failures: list[tuple[str, str]] = []

    # Exactly the media keys, adopted or not. Taking them from classification
    # rather than from the raw listing is what keeps a `.jpg` thumbnail from
    # looking like an image in want of a thumbnail of its own.
    for media_key in sorted(set(result.media) | set(result.unindexed)):
        if media_key in result.thumbnails or media_key in result.ambiguous:
            continue
        if extension_of(media_key) not in exts:
            continue

        sidecar_key = result.media.get(media_key)
        needs_duration = False
        if sidecar_key is not None and want_duration:
            try:
                payload = read_sidecar(bucket, sidecar_key)
            except SidecarUnreadable as exc:
                failures.append((sidecar_key, str(exc)))
                continue
            needs_duration = bool(missing_fields(payload, ("duration_s",)))

        thumbs.append(
            Thumb(
                media_key=media_key,
                thumb_key=thumb_key_for(media_key),
                sidecar_key=sidecar_key,
                needs_duration=needs_duration,
            )
        )
    return thumbs, failures


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        # ffmpeg reads stdin for interactive keys and would swallow the
        # terminal out from under both front ends.
        stdin=subprocess.DEVNULL,
    )


def _last_error(process: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (process.stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else f"ffmpeg exited {process.returncode}"


def render(
    url: str,
    dest: Path,
    *,
    seek: float = DEFAULT_SEEK,
    width: int = DEFAULT_WIDTH,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Write one frame of `url` to `dest` as JPEG.

    `-ss` before `-i` is an input seek, which jumps rather than decoding up to
    the mark -- the difference between a range request and streaming the whole
    file to the five second point.

    A clip shorter than the seek point yields no frame at all, which is common
    enough in a phone library to be the normal case rather than an error, so it
    falls back to the first frame. The fallback is only tried when the seek was
    past the start, or a genuinely broken file would be decoded twice.
    """
    require_ffmpeg()

    attempts = [seek, 0.0] if seek > 0 else [0.0]
    last = ""
    for attempt in attempts:
        command = [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            "-y",
            "-ss", f"{attempt:g}",
            "-i", url,
            "-frames:v", "1",
            "-an",
            # min() rather than a plain width so a small clip is never blown up
            # to 640 and stored bigger than the frame it came from. -2 keeps
            # the aspect ratio and an even height, which JPEG's chroma
            # subsampling requires.
            "-vf", rf"scale=w=min({width}\,iw):h=-2",
            "-q:v", str(JPEG_QUALITY),
            str(dest),
        ]
        try:
            process = _run(command, timeout)
        except subprocess.TimeoutExpired as exc:
            raise ThumbnailFailed(f"ffmpeg timed out after {timeout}s") from exc

        if process.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return
        last = _last_error(process)

    raise ThumbnailFailed(last or "ffmpeg produced no frame")


def probe_duration(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> float | None:
    """Runtime in seconds, or None when ffprobe will not say.

    Returns None rather than raising: an absent duration is a state the archive
    already understands, and it is not worth failing a thumbnail that rendered
    fine over.
    """
    require_ffmpeg()
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        url,
    ]
    try:
        process = _run(command, timeout)
    except subprocess.TimeoutExpired:
        return None
    if process.returncode != 0:
        return None
    try:
        value = float((process.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _url_for(bucket: Bucket, key: str) -> str:
    opener = getattr(bucket, "presigned_url", None)
    if opener is None:
        raise ThumbnailFailed(
            "this bucket cannot produce a URL for ffmpeg to read"
        )
    return opener(key)


def apply(
    bucket: Bucket,
    thumbs: list[Thumb],
    *,
    seek: float = DEFAULT_SEEK,
    width: int = DEFAULT_WIDTH,
    timeout: int = DEFAULT_TIMEOUT,
    on_start: Callable[[Thumb, int, int], None] | None = None,
) -> tuple[int, list[tuple[str, str]]]:
    """Render and upload each thumbnail. Returns the count and any failures.

    One bad file does not stop the run. Each thumbnail is independent and
    entirely derived, so a partial pass is a safe state -- the files that
    failed simply still have no thumbnail, which SPEC.md lists as normal.

    `on_start` is called before each render so both front ends can say which
    file they are on; a decode of a remote video is slow enough that silence
    reads as a hang.
    """
    require_ffmpeg()

    written = 0
    failures: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="keepsake-thumbs-") as workspace:
        scratch = Path(workspace) / "frame.jpg"
        for position, thumb in enumerate(thumbs, start=1):
            if on_start is not None:
                on_start(thumb, position, len(thumbs))
            try:
                url = _url_for(bucket, thumb.media_key)
                render(url, scratch, seek=seek, width=width, timeout=timeout)
                image = scratch.read_bytes()

                # SPEC.md write order: the image lands before anything points
                # at it.
                bucket.put(thumb.thumb_key, image, content_type=THUMB_TYPE)

                if thumb.sidecar_key is not None:
                    fields: dict[str, Any] = {
                        # SPEC.md: filename relative to the sidecar's directory.
                        "thumbnail": thumb.thumb_key.rsplit("/", 1)[-1],
                    }
                    if thumb.needs_duration:
                        fields["duration_s"] = probe_duration(url, timeout=timeout)
                    merge_sidecar(
                        bucket,
                        thumb.sidecar_key,
                        fields,
                        # We just wrote the image, so its name is a fact worth
                        # asserting. The runtime is not ours to insist on: if
                        # something recorded one between the plan and now, it
                        # stays.
                        only_if_absent=("duration_s",),
                    )
            except Exception as exc:  # noqa: BLE001 - reported verbatim
                failures.append((thumb.media_key, f"{type(exc).__name__}: {exc}"))
                continue
            finally:
                scratch.unlink(missing_ok=True)
            written += 1

    return written, failures
