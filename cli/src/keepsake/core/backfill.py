"""Fill machine facts into sidecars that already have one.

`core/adopt.py` covers media with no sidecar. This covers the other case: a
sidecar that exists but is missing something the file itself knows. The nine
videos adopted before the header parser was written have no `recorded_at` and
no `duration_s`, and both are sitting in their own `mvhd` box.

Reading it remotely costs about two range requests and a few hundred bytes --
`read_movie_header` was built to take a file object for exactly this, and
`RangeReader` supplies one. That is cheap enough to run in the ordinary `sync`
pass rather than behind a flag, which matters: a `length` column that only
fills when you remember to pass an option mostly stays empty.

Nothing here overwrites. `backfill_sidecar` applies only absent fields, so a
date somebody typed outranks one a parser derived, always.

Two costs worth naming. A file whose header holds no date is re-probed on
every run, since there is no place to record "asked, nothing there" that would
not itself be a fact invented about the file. And only ISO base media format is
read here; anything else waits for the ffprobe pass, which decodes the header
anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from keepsake.core.classify import Classification
from keepsake.core.moov import read_movie_header
from keepsake.core.sidecar import (
    SidecarUnreadable,
    backfill_sidecar,
    missing_fields,
    read_sidecar,
)
from keepsake.core.survey import extension_of
from keepsake.storage.base import Bucket, open_range_reader

#: Containers `core/moov.py` can read: ISO base media format and its relatives.
#: SPEC.md warns that `.mp4` and `.mov` are both reasonable names for it, so
#: this list is about what the parser understands, not about brand names.
MOOV_EXTS = {".mov", ".mp4", ".m4v", ".3gp", ".3g2", ".m4a"}

#: What a movie header can tell us. Both are SPEC.md optional fields.
BACKFILL_FIELDS = ("recorded_at", "duration_s")


@dataclass
class Fill:
    """One sidecar and the fields that would be added to it."""

    media_key: str
    sidecar_key: str
    fields: dict[str, Any] = field(default_factory=dict)


def plan(
    bucket: Bucket,
    result: Classification,
    *,
    wanted: tuple[str, ...] = BACKFILL_FIELDS,
) -> tuple[list[Fill], list[tuple[str, str]]]:
    """What a backfill run would write, plus anything it could not read.

    The headers really are read here rather than at apply time, so a dry run
    shows the actual values instead of promising to find some. That is the
    whole use of the dry run for this pass -- a date read out of a fifteen-year
    -old camcorder file is worth looking at before it lands in the archive.

    A file that simply has no readable header is not a failure and is not
    reported: absent metadata is a state the archive already understands. Real
    failures -- an unreadable sidecar, a bucket that will not answer -- are
    returned for the caller to show, so one bad object does not stop the run.
    """
    fills: list[Fill] = []
    failures: list[tuple[str, str]] = []

    for media_key, sidecar_key in sorted(result.media.items()):
        if extension_of(media_key) not in MOOV_EXTS:
            continue
        try:
            payload = read_sidecar(bucket, sidecar_key)
        except SidecarUnreadable as exc:
            failures.append((sidecar_key, str(exc)))
            continue

        absent = missing_fields(payload, wanted)
        if not absent:
            continue

        try:
            reader = open_range_reader(bucket, media_key)
            if reader is None:
                continue  # `check` reports a sidecar whose media is gone
            with reader:
                header = read_movie_header(reader)
        except Exception as exc:  # noqa: BLE001 - reported verbatim
            failures.append((media_key, f"{type(exc).__name__}: {exc}"))
            continue

        if header is None:
            continue

        found = {
            name: value
            for name in absent
            if (value := getattr(header, name, None)) is not None
        }
        if found:
            fills.append(Fill(media_key=media_key, sidecar_key=sidecar_key, fields=found))

    return fills, failures


def apply(bucket: Bucket, fills: list[Fill]) -> tuple[int, list[tuple[str, str]]]:
    """Write each fill. Returns how many sidecars changed, and any failures.

    A fill that turns out to be redundant -- someone filled the field between
    plan and apply -- writes nothing and is not counted, because
    `backfill_sidecar` re-reads before deciding.
    """
    written = 0
    failures: list[tuple[str, str]] = []
    for fill in fills:
        try:
            applied = backfill_sidecar(bucket, fill.sidecar_key, fill.fields)
        except Exception as exc:  # noqa: BLE001 - reported verbatim
            failures.append((fill.sidecar_key, f"{type(exc).__name__}: {exc}"))
            continue
        if applied:
            written += 1
    return written, failures
