"""Writing a sidecar that already exists.

Three writers need this: the TUI editor saving a typed title, the `mvhd`
backfill filling in machine facts, and the thumbnail pass recording the image
it just uploaded. `core/adopt.py` is deliberately not one of them -- it creates
sidecars for media that has none, which is a different problem with no stored
object to merge against.

They all face SPEC.md's concurrency rule. Sidecar writes are last-writer-wins,
and the unsafe window is the whole edit session rather than the request, so a
writer that PUTs an object it loaded earlier silently discards anything written
in between. The answer SPEC.md gives is to re-read immediately before writing
and merge field-by-field, which narrows the window to a single request without
closing it. B2's S3 API has no conditional writes, so it cannot be closed.

That rule is subtle enough -- it is also what preserves unknown fields, which
SPEC.md requires so clients of different versions can coexist -- that it should
exist in exactly one place. This is that place.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from keepsake.storage.base import Bucket

#: The order fields are written in, matching what `adopt.sidecar_payload`
#: emits so a sidecar created by adoption and one edited afterwards do not
#: differ by field order alone. Fields SPEC.md does not name -- and anything a
#: newer client wrote that we do not recognise -- keep their existing relative
#: order at the end, since we have no basis for placing them.
FIELD_ORDER = (
    "schema",
    "id",
    "file",
    "title",
    "recorded_at",
    "uploaded_at",
    "tags",
    "location",
    "notes",
    "duration_s",
    "size_bytes",
    "media_type",
    "sha256",
    "thumbnail",
)


class SidecarUnreadable(Exception):
    """The stored sidecar is missing or is not a JSON object.

    Merging needs something to merge onto. Writing only the new fields would
    produce a sidecar without `schema`, `id`, `file` or `uploaded_at`, which
    SPEC.md requires -- worse than leaving the broken one in place, where
    `check` can report it.
    """


def canonical(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`payload` with known fields in FIELD_ORDER, unknown ones after."""
    known = {name: payload[name] for name in FIELD_ORDER if name in payload}
    unknown = {name: value for name, value in payload.items() if name not in known}
    return {**known, **unknown}


def serialize(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(canonical(payload), indent=2, ensure_ascii=False).encode("utf-8")


def read_sidecar(
    bucket: Bucket,
    sidecar_key: str,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The stored sidecar as a dict, or `fallback` when it cannot be read.

    Raises SidecarUnreadable when there is no fallback to fall back to.
    """
    try:
        stored = json.loads(bucket.get(sidecar_key))
    except (KeyError, json.JSONDecodeError) as exc:
        if fallback is None:
            raise SidecarUnreadable(f"{sidecar_key}: {type(exc).__name__}") from exc
        return dict(fallback)
    if not isinstance(stored, dict):
        if fallback is None:
            raise SidecarUnreadable(f"{sidecar_key}: not a JSON object")
        return dict(fallback)
    return stored


def write_sidecar(bucket: Bucket, sidecar_key: str, payload: Mapping[str, Any]) -> None:
    bucket.put(sidecar_key, serialize(payload), content_type="application/json")


def _absent(value: Any) -> bool:
    """Whether a stored field counts as not there.

    An empty string is treated as absent: it is what an editor writes when
    someone clears a box and something else fills it back in, and no field
    SPEC.md defines is meaningfully empty-but-present.
    """
    return value is None or value == ""


def merge_sidecar(
    bucket: Bucket,
    sidecar_key: str,
    fields: Mapping[str, Any],
    *,
    only_if_absent: tuple[str, ...] = (),
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply `fields` to the stored sidecar and write it back.

    A value of None removes its field, which is how an edit that clears a text
    box reaches the bucket.

    Fields named in `only_if_absent` are written just when the stored sidecar
    lacks them, so one write can carry both policies at once: the thumbnail
    pass knows the filename it just uploaded and should say so, while the
    duration it probed on the way must not displace one already recorded.

    Returns the payload as written.
    """
    stored = read_sidecar(bucket, sidecar_key, fallback=fallback)
    for name, value in fields.items():
        if name in only_if_absent:
            if not _absent(value) and _absent(stored.get(name)):
                stored[name] = value
        elif value is None:
            stored.pop(name, None)
        else:
            stored[name] = value
    write_sidecar(bucket, sidecar_key, stored)
    return canonical(stored)


def backfill_sidecar(
    bucket: Bucket,
    sidecar_key: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Fill only the fields the stored sidecar lacks. Returns what was applied.

    Never overwrites a value that is already there. A date somebody typed is
    worth more than one a parser derived, and a machine pass that silently
    replaced it would be the kind of bug nobody notices until the wrong date is
    the only one left. Fields already present are dropped from the write, and
    when that leaves nothing the sidecar is not rewritten at all -- a no-op run
    should not create an object version.

    The stored sidecar is re-read here rather than trusting a plan built
    earlier, so what gets skipped reflects the bucket at the moment of writing.
    """
    stored = read_sidecar(bucket, sidecar_key)
    applied = {
        name: value
        for name, value in fields.items()
        if not _absent(value) and _absent(stored.get(name))
    }
    if not applied:
        return {}
    stored.update(applied)
    write_sidecar(bucket, sidecar_key, stored)
    return applied


def missing_fields(payload: Mapping[str, Any], wanted: tuple[str, ...]) -> tuple[str, ...]:
    """Which of `wanted` the payload does not already carry.

    Same emptiness test the writers apply, so a plan built with this agrees
    with what the write will do.
    """
    return tuple(name for name in wanted if _absent(payload.get(name)))
