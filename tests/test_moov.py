"""Reading recorded_at and duration_s out of an MP4/QuickTime header.

Fixtures are built byte by byte rather than checked in as sample videos: the
boxes under test are about forty bytes, and a hand-built one states exactly
what is being asserted.
"""

from __future__ import annotations

import io
import struct
from datetime import datetime, timedelta, timezone

from keepsake.core.moov import QUICKTIME_EPOCH, read_movie_header


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def mvhd_v0(creation: int = 0, timescale: int = 600, duration: int = 0) -> bytes:
    return box(
        b"mvhd",
        struct.pack(">B3x", 0)
        + struct.pack(">IIII", creation, creation, timescale, duration)
        + b"\x00" * 80,
    )


def mvhd_v1(creation: int = 0, timescale: int = 600, duration: int = 0) -> bytes:
    return box(
        b"mvhd",
        struct.pack(">B3x", 1)
        + struct.pack(">QQIQ", creation, creation, timescale, duration)
        + b"\x00" * 80,
    )


def movie(mvhd: bytes, *, moov_last: bool = False) -> io.BytesIO:
    ftyp = box(b"ftyp", b"qt  " + b"\x00" * 8)
    mdat = box(b"mdat", b"\x00" * 64)
    moov = box(b"moov", mvhd)
    order = (ftyp, mdat, moov) if moov_last else (ftyp, moov, mdat)
    return io.BytesIO(b"".join(order))


def seconds_since_1904(when: datetime) -> int:
    return int((when - QUICKTIME_EPOCH).total_seconds())


#: A plausible stamp, for fixtures whose date is not what is under test.
SOME_STAMP = seconds_since_1904(datetime(2026, 4, 12, tzinfo=timezone.utc))


class TestDuration:
    def test_divides_duration_by_timescale(self):
        header = read_movie_header(movie(mvhd_v0(timescale=600, duration=247_200)))
        assert header.duration_s == 412.0

    def test_reads_the_64_bit_layout(self):
        header = read_movie_header(movie(mvhd_v1(timescale=1000, duration=90_000)))
        assert header.duration_s == 90.0

    def test_absent_when_timescale_is_zero(self):
        # A date as well, so this asserts "no duration" rather than tripping
        # the "nothing readable at all" path.
        dated = mvhd_v0(creation=SOME_STAMP, timescale=0, duration=1000)
        assert read_movie_header(movie(dated)).duration_s is None

    def test_absent_for_the_unknown_sentinel(self):
        dated = mvhd_v0(creation=SOME_STAMP, duration=0xFFFFFFFF)
        assert read_movie_header(movie(dated)).duration_s is None


class TestRecordedAt:
    def test_counts_from_1904_not_1970(self):
        stamp = seconds_since_1904(datetime(2026, 4, 12, 18, 30, tzinfo=timezone.utc))
        header = read_movie_header(movie(mvhd_v0(creation=stamp, duration=600)))
        assert header.recorded_at == "2026-04-12"

    def test_is_date_only(self):
        """Apple writes local wall-clock with no zone; a time would be a lie."""
        stamp = seconds_since_1904(datetime(2026, 4, 12, 23, 59, tzinfo=timezone.utc))
        header = read_movie_header(movie(mvhd_v0(creation=stamp, duration=600)))
        assert header.recorded_at == "2026-04-12"
        assert "T" not in header.recorded_at

    def test_zero_means_unknown(self):
        header = read_movie_header(movie(mvhd_v0(creation=0, duration=600)))
        assert header.recorded_at is None

    def test_a_future_stamp_is_rejected(self):
        ahead = datetime.now(timezone.utc) + timedelta(days=400)
        broken = mvhd_v0(creation=seconds_since_1904(ahead), duration=600)
        assert read_movie_header(movie(broken)).recorded_at is None

    def test_reads_the_64_bit_layout(self):
        stamp = seconds_since_1904(datetime(1998, 7, 4, tzinfo=timezone.utc))
        header = read_movie_header(movie(mvhd_v1(creation=stamp, duration=1000)))
        assert header.recorded_at == "1998-07-04"


class TestTolerance:
    def test_finds_moov_at_the_end_of_the_file(self):
        """Only faststart files put moov first; a camera usually does not."""
        stamp = seconds_since_1904(datetime(2026, 5, 22, tzinfo=timezone.utc))
        header = read_movie_header(
            movie(mvhd_v0(creation=stamp, duration=600), moov_last=True)
        )
        assert header.recorded_at == "2026-05-22"

    def test_returns_none_for_a_file_that_is_not_a_movie(self):
        assert read_movie_header(io.BytesIO(b"not a movie, just some bytes")) is None

    def test_returns_none_for_an_empty_file(self):
        assert read_movie_header(io.BytesIO(b"")) is None

    def test_returns_none_when_truncated_mid_box(self):
        data = movie(mvhd_v0(duration=600)).getvalue()
        assert read_movie_header(io.BytesIO(data[: len(data) // 2])) is None

    def test_returns_none_when_there_is_no_mvhd(self):
        assert read_movie_header(movie(box(b"trak", b"\x00" * 32))) is None

    def test_a_nonsense_box_size_does_not_hang(self):
        broken = struct.pack(">I4s", 4, b"moov") + b"\x00" * 32
        assert read_movie_header(io.BytesIO(broken)) is None

    def test_header_with_nothing_readable_is_none(self):
        """No date and no duration is the same as no header at all."""
        assert read_movie_header(movie(mvhd_v0(creation=0, duration=0))) is None
