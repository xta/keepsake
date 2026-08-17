"""Reading a few bytes out of a remote object.

`read_movie_header` was written to take a file object so it could one day be
pointed at a bucket. These tests are that day: the same parser, the same
fixtures as `test_moov.py`, reached through range requests instead of a
BytesIO. The mvhd box builders are imported from there rather than rebuilt,
since a second hand-packed copy of the layout would be one more thing to keep
in step.
"""

from __future__ import annotations

import pytest

from keepsake.core.moov import read_movie_header
from keepsake.storage.base import RangeReader, open_range_reader
from keepsake.storage.local import LocalDirBucket
from test_moov import SOME_STAMP, box, movie, mvhd_v0

ALPHABET = b"abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def bucket(tmp_path):
    bucket = LocalDirBucket(tmp_path, readonly=False)
    bucket.seed("letters.bin", ALPHABET)
    return bucket


class TestGetRange:
    def test_end_is_inclusive_as_http_counts_it(self, bucket):
        assert bucket.get_range("letters.bin", 0, 3) == b"abcd"

    def test_reads_from_the_middle(self, bucket):
        assert bucket.get_range("letters.bin", 10, 12) == b"klm"

    def test_a_range_running_past_the_end_returns_what_is_there(self, bucket):
        assert bucket.get_range("letters.bin", 24, 99) == b"yz"

    def test_a_range_starting_past_the_end_is_empty(self, bucket):
        """B2 answers 416 here; both backends have to agree on empty, or a
        parser walking a malformed header behaves differently per backend."""
        assert bucket.get_range("letters.bin", 99, 120) == b""

    def test_a_missing_key_raises(self, bucket):
        with pytest.raises(KeyError):
            bucket.get_range("nope.bin", 0, 3)


class TestRangeReader:
    def reader(self, bucket, **kwargs) -> RangeReader:
        return RangeReader(bucket, "letters.bin", len(ALPHABET), **kwargs)

    def test_reads_sequentially(self, bucket):
        fh = self.reader(bucket)
        assert fh.read(3) == b"abc"
        assert fh.read(3) == b"def"
        assert fh.tell() == 6

    def test_seeks_from_the_start(self, bucket):
        fh = self.reader(bucket)
        fh.seek(10)
        assert fh.read(3) == b"klm"

    def test_seeks_relative_and_from_the_end(self, bucket):
        fh = self.reader(bucket)
        fh.seek(10)
        fh.seek(2, 1)
        assert fh.read(1) == b"m"
        fh.seek(-2, 2)
        assert fh.read(2) == b"yz"

    def test_seek_to_the_end_reports_the_size(self, bucket):
        """The first thing every header parser does, to learn where the file
        stops."""
        fh = self.reader(bucket)
        fh.seek(0, 2)
        assert fh.tell() == len(ALPHABET)

    def test_reading_past_the_end_is_empty(self, bucket):
        fh = self.reader(bucket)
        fh.seek(100)
        assert fh.read(4) == b""

    def test_a_short_read_at_the_end_returns_what_is_left(self, bucket):
        fh = self.reader(bucket)
        fh.seek(24)
        assert fh.read(10) == b"yz"

    def test_read_all_returns_the_rest(self, bucket):
        fh = self.reader(bucket)
        fh.seek(23)
        assert fh.read() == b"xyz"

    def test_nearby_reads_share_one_request(self, bucket):
        """The reason for the cached window. A box walk reads eight bytes at a
        time, and a request per read would make a remote header parse cost
        dozens of round trips."""
        fh = self.reader(bucket, chunk_size=16)
        fh.read(4)
        fh.seek(8)
        fh.read(4)
        assert fh.requests == 1

    def test_a_distant_seek_refills(self, bucket):
        fh = self.reader(bucket, chunk_size=8)
        fh.read(4)
        fh.seek(20)
        fh.read(4)
        assert fh.requests == 2

    def test_invalid_whence_is_refused(self, bucket):
        with pytest.raises(ValueError):
            self.reader(bucket).seek(0, 9)


class TestOpenRangeReader:
    def test_none_when_the_object_is_absent(self, bucket):
        assert open_range_reader(bucket, "nope.bin") is None

    def test_knows_the_size_without_reading_the_object(self, bucket):
        fh = open_range_reader(bucket, "letters.bin")
        assert fh.seek(0, 2) == len(ALPHABET)
        assert fh.requests == 0


class TestMovieHeaderOverRanges:
    """The parser, unchanged, reading a bucket instead of a file."""

    def seed_movie(self, bucket, *, moov_last: bool) -> None:
        data = movie(
            mvhd_v0(creation=SOME_STAMP, timescale=600, duration=247_200),
            moov_last=moov_last,
        ).getvalue()
        bucket.seed("clip.mp4", data)

    @pytest.mark.parametrize("moov_last", [False, True])
    def test_reads_the_same_values_as_a_local_file(self, bucket, moov_last):
        self.seed_movie(bucket, moov_last=moov_last)

        with open_range_reader(bucket, "clip.mp4") as fh:
            header = read_movie_header(fh)

        assert header.duration_s == 412.0
        assert header.recorded_at == "2026-04-12"

    def test_a_large_file_still_costs_a_couple_of_requests(self, bucket):
        """The property the whole approach rests on.

        A real video is gigabytes with `moov` at the end, so the parser has to
        seek past the payload rather than read through it. Two megabytes of
        `mdat` here is enough to prove the walk jumps: at a 64 KB window,
        streaming to the end would take thirty-odd requests.
        """
        ftyp = box(b"ftyp", b"qt  " + b"\x00" * 8)
        mdat = box(b"mdat", b"\x00" * (2 * 1024 * 1024))
        moov = box(b"moov", mvhd_v0(creation=SOME_STAMP, timescale=600, duration=247_200))
        bucket.seed("big.mp4", ftyp + mdat + moov)

        fh = open_range_reader(bucket, "big.mp4")
        header = read_movie_header(fh)

        assert header.duration_s == 412.0
        assert fh.requests <= 3

    def test_a_file_that_is_not_a_movie_returns_none(self, bucket):
        bucket.seed("notes.mp4", b"nothing like a box header")

        with open_range_reader(bucket, "notes.mp4") as fh:
            assert read_movie_header(fh) is None
