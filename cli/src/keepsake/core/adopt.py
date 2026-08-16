"""Generate stub sidecars for media that has none.

A stub records only what the bucket already knows for certain: identity, the
file's own name, when it landed, its size, and its media type. Nothing is
guessed.

In particular `title` and `recorded_at` are left absent rather than derived
from the filename or the path. A path like `2026/05/IMG_0002.MOV` implies a
year and a month, but SPEC.md requires `YYYY-MM-DD` or RFC 3339, and inventing
a day to satisfy the format would put a fact in the archive that nobody
established. An absent field is honest and easy to fill in later; a wrong one
looks authoritative forever.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from keepsake.core.classify import Classification
from keepsake.core.survey import MEDIA_EXTS, extension_of
from keepsake.models import SCHEMA_VERSION
from keepsake.storage.base import (
    SIDECAR_SUFFIX,
    Bucket,
    MediaWriteRefused,
    ReadOnlyBucket,
    has_extension,
)

# Extensions the stdlib does not know, or knows differently than we want.
MEDIA_TYPE_OVERRIDES = {
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".mkv": "video/x-matroska",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".3gp": "video/3gpp",
}


def guess_media_type(key: str) -> str | None:
    if not has_extension(key):
        return None
    base = key.rsplit("/", 1)[-1]
    ext = "." + base.rsplit(".", 1)[-1].lower()
    if ext in MEDIA_TYPE_OVERRIDES:
        return MEDIA_TYPE_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(base.lower())
    return guessed


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sidecar_payload(
    *,
    filename: str,
    new_id: str,
    uploaded_at: str,
    size_bytes: int | None = None,
    media_type: str | None = None,
    thumbnail: str | None = None,
    title: str | None = None,
    recorded_at: str | None = None,
    duration_s: float | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    """Build a sidecar body. The one place either writer constructs one.

    Adoption and upload learn different amounts about a file -- adoption knows
    only what the bucket listing says, while upload has the file itself and can
    read its header and hash it -- but both must produce the same shape, in the
    same field order, or two sidecars written a minute apart would diff for no
    reason. Optional fields stay absent rather than null: SPEC.md's required
    set is the four machine facts, and an absent field is honest where an empty
    one is noise.
    """
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "id": new_id,
        "file": filename,
    }
    if title:
        payload["title"] = title
    if recorded_at:
        payload["recorded_at"] = recorded_at
    payload["uploaded_at"] = uploaded_at
    if duration_s is not None:
        payload["duration_s"] = duration_s
    if size_bytes is not None:
        payload["size_bytes"] = size_bytes
    if media_type:
        payload["media_type"] = media_type
    if sha256:
        payload["sha256"] = sha256
    if thumbnail:
        payload["thumbnail"] = thumbnail
    return payload


@dataclass
class Stub:
    media_key: str
    sidecar_key: str
    payload: dict[str, Any]

    def serialize(self) -> bytes:
        return json.dumps(self.payload, indent=2, ensure_ascii=False).encode("utf-8")


def plan(
    result: Classification,
    *,
    new_id,
    include_unrecognised: bool = False,
) -> list[Stub]:
    """Stubs that would be written, for every unindexed media file.

    `new_id` is injected so tests can pin identifiers; production passes a UUIDv7
    factory.

    Keys whose extension is not recognised media are skipped by default, so a
    stray `notes.txt` never becomes a library item. Nothing is lost by that:
    classification still lists the file as unindexed and `check` still reports
    it, so a real video in an unfamiliar format is visible and can be adopted
    deliberately with `include_unrecognised`.
    """
    stubs: list[Stub] = []
    for media_key in result.unindexed:
        if not include_unrecognised and extension_of(media_key) not in MEDIA_EXTS:
            continue
        obj = result.objects[media_key]

        # Classification recognises a thumbnail before its media has a sidecar,
        # so when one is already sitting there the stub can record it instead
        # of leaving the field blank on a file whose thumbnail exists.
        thumbnail = result.thumbnails.get(media_key)

        payload = sidecar_payload(
            filename=media_key.rsplit("/", 1)[-1],
            new_id=new_id(),
            # `uploaded_at` is when the object landed in the bucket, which is
            # what the field means. For files put here by other means it is the
            # closest true answer available.
            uploaded_at=rfc3339(obj.last_modified or datetime.now(timezone.utc)),
            size_bytes=obj.size,
            media_type=guess_media_type(media_key),
            # SPEC.md: filename relative to the sidecar's own directory.
            thumbnail=thumbnail.rsplit("/", 1)[-1] if thumbnail else None,
        )

        stubs.append(
            Stub(
                media_key=media_key,
                # SPEC.md: writers emit lowercase suffixes.
                sidecar_key=media_key + SIDECAR_SUFFIX,
                payload=payload,
            )
        )
    return stubs


def apply(bucket: Bucket, stubs: list[Stub]) -> tuple[int, list[tuple[str, str]]]:
    """Write each stub. Returns the number written and any failures.

    Sidecars are the commit marker in SPEC.md's write order, and the media
    files already exist, so each write completes one file's adoption.

    A failed write does not abort the run. Each sidecar is an independent
    commit marker, so a partial adoption is a safe state -- the files that did
    not get one stay unindexed, which is a state the tool already understands.
    Stopping at the first error would just adopt fewer of them.

    The guard exceptions are the exception. A read-only bucket or a refused
    media write means the caller asked for something it should never have been
    able to ask for, which is a bug rather than a bad object, so those still
    raise.
    """
    written = 0
    failures: list[tuple[str, str]] = []
    for stub in stubs:
        try:
            bucket.put(
                stub.sidecar_key, stub.serialize(), content_type="application/json"
            )
        except (ReadOnlyBucket, MediaWriteRefused):
            raise
        except Exception as exc:  # noqa: BLE001 - reported verbatim to the caller
            failures.append((stub.sidecar_key, f"{type(exc).__name__}: {exc}"))
            continue
        written += 1
    return written, failures
