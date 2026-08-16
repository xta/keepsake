"""Read a movie's recording date and runtime out of its own header.

MP4 and QuickTime both keep the two facts we most want -- when the camera
started recording, and how long the result runs -- in a small `mvhd` box. No
ffmpeg, no transcode, no upload: two seeks and a handful of bytes.

This takes a file object rather than a path so the same parser can later read a
remote file through range requests. Nothing here assumes local disk beyond the
ability to seek.

It never raises on bad input. A file that is not ISO base media format, or is
truncated, or was written by something creative, returns None -- an absent date
is a state the archive already understands, and a parser that halts an upload
over an unreadable header would be worse than no parser.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import BinaryIO, Iterator

#: mvhd timestamps count seconds from 1904-01-01, not the Unix epoch.
QUICKTIME_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

#: A malformed size field could otherwise walk forever.
MAX_BOXES = 128

#: mvhd writes this when it does not know the duration.
UNKNOWN_DURATION = 0xFFFFFFFF


@dataclass(frozen=True)
class MovieHeader:
    #: `YYYY-MM-DD`. Never a time -- see `_creation_date`.
    recorded_at: str | None = None
    duration_s: float | None = None

    def __bool__(self) -> bool:
        return self.recorded_at is not None or self.duration_s is not None


def _boxes(fh: BinaryIO, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Yield `(type, body_start, body_end)` for each box until `end`.

    Box layout is `size(4) type(4)`, where size counts the header too. A size
    of 1 means the real 64-bit size follows the type; 0 means "to the end".
    """
    position = fh.tell()
    for _ in range(MAX_BOXES):
        if position + 8 > end:
            return
        fh.seek(position)
        header = fh.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        body = position + 8

        if size == 1:
            extra = fh.read(8)
            if len(extra) < 8:
                return
            size = struct.unpack(">Q", extra)[0]
            body = position + 16
        elif size == 0:
            size = end - position

        stop = position + size
        if size < 8 or stop > end:
            return
        yield kind, body, stop
        position = stop


def _find(fh: BinaryIO, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    fh.seek(start)
    for found, body, stop in _boxes(fh, end):
        if found == kind:
            return body, stop
    return None


def _creation_date(seconds: int) -> str | None:
    """A QuickTime timestamp as `YYYY-MM-DD`, or None when implausible.

    Deliberately date-only. Apple writes this field as local wall-clock time
    with no zone attached, so treating it as UTC would shift a late-evening
    recording onto the wrong day and, worse, would look precise while doing it.
    A date is the most we actually know. (`com.apple.quicktime.creationdate` in
    `udta/meta` carries a real offset if the instant ever matters.)
    """
    if seconds <= 0:
        return None
    try:
        moment = QUICKTIME_EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        return None
    # A stamp in the future is a broken clock or a misparse, not a fact.
    if moment > datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return moment.strftime("%Y-%m-%d")


def _parse_mvhd(payload: bytes) -> MovieHeader:
    version = payload[0]
    if version == 1:
        offsets = {"creation": (4, ">Q", 8), "timescale": (20, ">I", 4), "duration": (24, ">Q", 8)}
        needed = 32
    else:
        offsets = {"creation": (4, ">I", 4), "timescale": (12, ">I", 4), "duration": (16, ">I", 4)}
        needed = 20
    if len(payload) < needed:
        return MovieHeader()

    def field(name: str) -> int:
        at, fmt, width = offsets[name]
        return struct.unpack(fmt, payload[at : at + width])[0]

    timescale = field("timescale")
    duration = field("duration")

    runtime: float | None = None
    if timescale > 0 and duration > 0 and duration != UNKNOWN_DURATION:
        runtime = duration / timescale

    return MovieHeader(recorded_at=_creation_date(field("creation")), duration_s=runtime)


def read_movie_header(fh: BinaryIO) -> MovieHeader | None:
    """The recording date and runtime from an MP4/QuickTime header.

    Returns None when the file is not one, or holds no readable `mvhd`.
    """
    try:
        fh.seek(0, 2)
        end = fh.tell()
        fh.seek(0)

        moov = _find(fh, 0, end, b"moov")
        if moov is None:
            return None
        mvhd = _find(fh, moov[0], moov[1], b"mvhd")
        if mvhd is None:
            return None

        fh.seek(mvhd[0])
        payload = fh.read(min(mvhd[1] - mvhd[0], 128))
    except (OSError, struct.error, ValueError):
        return None

    if len(payload) < 20:
        return None
    header = _parse_mvhd(payload)
    return header if header else None


def read_movie_header_at(path) -> MovieHeader | None:
    """`read_movie_header` for a path on disk. Returns None if unreadable."""
    try:
        with open(path, "rb") as fh:
            return read_movie_header(fh)
    except OSError:
        return None
