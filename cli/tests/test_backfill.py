"""Filling a movie's own header into a sidecar that already exists.

The pass that reaches video adopted before the header parser was written: the
facts are sitting in the file, and nobody has to be asked for them.
"""

from __future__ import annotations

import json

import pytest

from keepsake.core import backfill
from keepsake.core.classify import classify
from keepsake.storage.local import LocalDirBucket
from test_moov import SOME_STAMP, movie, mvhd_v0

MEDIA = "2026/05/clip.mp4"
SIDECAR = MEDIA + ".json"


@pytest.fixture
def bucket(tmp_path):
    return LocalDirBucket(tmp_path, readonly=False)


def seed_movie(bucket, key=MEDIA, *, creation=SOME_STAMP, timescale=600, duration=247_200):
    data = movie(
        mvhd_v0(creation=creation, timescale=timescale, duration=duration)
    ).getvalue()
    bucket.seed(key, data)


def seed_sidecar(bucket, key=SIDECAR, **extra):
    bucket.seed(
        key,
        json.dumps(
            {
                "schema": 1,
                "id": "01a0098c-ebfd-7e9f-bac0-ca39f3495b09",
                "file": key.rsplit("/", 1)[-1].removesuffix(".json"),
                "uploaded_at": "2026-05-01T00:00:00Z",
                **extra,
            }
        ).encode(),
    )


def run(bucket):
    fills, read_failures = backfill.plan(bucket, classify(bucket.list()))
    written, failures = backfill.apply(bucket, fills)
    return fills, read_failures, written, failures


class TestPlan:
    def test_offers_both_fields_when_the_sidecar_has_neither(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket)

        fills, _ = backfill.plan(bucket, classify(bucket.list()))

        assert len(fills) == 1
        assert fills[0].sidecar_key == SIDECAR
        assert fills[0].fields == {"recorded_at": "2026-04-12", "duration_s": 412.0}

    def test_offers_only_the_missing_one(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket, recorded_at="1999-01-01")

        fills, _ = backfill.plan(bucket, classify(bucket.list()))

        assert fills[0].fields == {"duration_s": 412.0}

    def test_skips_a_sidecar_that_has_everything(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket, recorded_at="1999-01-01", duration_s=1.0)

        fills, _ = backfill.plan(bucket, classify(bucket.list()))

        assert fills == []

    def test_skips_media_with_no_sidecar(self, bucket):
        """Adoption's job. Backfill only touches sidecars that exist."""
        seed_movie(bucket)

        fills, _ = backfill.plan(bucket, classify(bucket.list()))

        assert fills == []

    def test_skips_a_container_the_parser_cannot_read(self, bucket):
        bucket.seed("2026/05/tape.avi", b"RIFF....AVI ")
        seed_sidecar(bucket, "2026/05/tape.avi.json")

        fills, failures = backfill.plan(bucket, classify(bucket.list()))

        assert fills == []
        assert failures == []

    def test_a_movie_with_no_readable_header_is_not_a_failure(self, bucket):
        """An absent date is a state the archive already understands, so it is
        skipped quietly rather than reported as something gone wrong."""
        bucket.seed(MEDIA, b"not a movie at all")
        seed_sidecar(bucket)

        fills, failures = backfill.plan(bucket, classify(bucket.list()))

        assert fills == []
        assert failures == []

    def test_an_unreadable_sidecar_is_reported_and_the_run_goes_on(self, bucket):
        seed_movie(bucket)
        bucket.seed(SIDECAR, b"{ broken")
        seed_movie(bucket, "2026/05/other.mp4")
        seed_sidecar(bucket, "2026/05/other.mp4.json")

        fills, failures = backfill.plan(bucket, classify(bucket.list()))

        assert [key for key, _ in failures] == [SIDECAR]
        assert [fill.sidecar_key for fill in fills] == ["2026/05/other.mp4.json"]


class TestApply:
    def test_writes_the_fields(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket)

        _, _, written, failures = run(bucket)

        assert (written, failures) == (1, [])
        stored = json.loads(bucket.get(SIDECAR))
        assert stored["recorded_at"] == "2026-04-12"
        assert stored["duration_s"] == 412.0

    def test_never_overwrites_a_value_already_there(self, bucket):
        """A date somebody typed outranks one a parser derived."""
        seed_movie(bucket)
        seed_sidecar(bucket, recorded_at="1985-07-04")

        run(bucket)

        assert json.loads(bucket.get(SIDECAR))["recorded_at"] == "1985-07-04"

    def test_leaves_the_title_alone(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket, title="Piano Recital")

        run(bucket)

        assert json.loads(bucket.get(SIDECAR))["title"] == "Piano Recital"

    def test_a_second_run_writes_nothing(self, bucket):
        seed_movie(bucket)
        seed_sidecar(bucket)
        run(bucket)
        before = bucket.get(SIDECAR)

        fills, _, written, _ = run(bucket)

        assert (fills, written) == ([], 0)
        assert bucket.get(SIDECAR) == before
