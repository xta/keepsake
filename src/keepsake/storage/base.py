"""Storage abstraction and the media-write guard.

Every bucket backend implements `Bucket`. The point of the abstraction is not
provider portability (we only target Backblaze B2 today) but testability: the
whole test suite runs against `LocalDirBucket` with no network and no creds.

Safety rule enforced here, at one chokepoint:

    This tool may write exactly three kinds of key -- the root index.json,
    `{media}.json` sidecars, and `{media}.{jpg,png,webp}` thumbnails.
    Everything else in the bucket is media and is read-only.

Media is only ever touched by a caller that passes `allow_media=True`, which
only an explicit user-invoked delete command sets. Nothing else can reach it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

# The one reserved key (SPEC.md "Reserved key"). A nested index.json is an
# ordinary sidecar, not this.
INDEX_KEY = "index.json"

SIDECAR_SUFFIX = ".json"

# Exactly the extensions SPEC.md names. Deliberately excludes ".jpeg" -- adding
# it here would be a silent divergence from our own spec.
THUMB_EXTS = (".jpg", ".png", ".webp")


@dataclass(frozen=True)
class Obj:
    """One object in a bucket, as returned by a listing."""

    key: str
    size: int
    last_modified: datetime | None = None
    etag: str | None = None


class MediaWriteRefused(Exception):
    """Raised when something tries to write or delete a media file."""


class ReadOnlyBucket(Exception):
    """Raised when a write is attempted on a bucket opened read-only."""


def is_writable_key(key: str) -> bool:
    """True if `key` is a companion this tool is allowed to create or replace.

    Conservative by design: it recognises the *shape* of a companion key
    without consulting the bucket. A thumbnail must look like
    `<name>.<mediaext>.<imgext>` -- stripping the image extension has to leave
    something that still carries an extension of its own. That keeps a
    standalone `vacation.jpg` (media) from being mistaken for a companion.

    Phase 2 note: once writes land, callers that already hold a Classification
    should prefer checking membership in its `thumbnails` map, which is exact.
    This function is the backstop for callers that don't.
    """
    if key == INDEX_KEY:
        return True
    if key.endswith(SIDECAR_SUFFIX):
        # `x.mp4.json` describes `x.mp4`; a bare `.json` at root would be the
        # reserved key, already handled above.
        return len(key) > len(SIDECAR_SUFFIX)
    for ext in THUMB_EXTS:
        if key.endswith(ext):
            stem = key[: -len(ext)]
            # `piano.mp4.jpg` -> stem `piano.mp4`, which has an extension. Good.
            # `vacation.jpg`  -> stem `vacation`, which does not. Treat as media.
            return "." in stem.rsplit("/", 1)[-1]
    return False


@runtime_checkable
class Bucket(Protocol):
    """A keepsake bucket. Read methods always work; writes are guarded."""

    name: str

    def list(self, prefix: str = "") -> Iterator[Obj]:
        """Yield every object under `prefix`, in whatever order the backend gives."""
        ...

    def get(self, key: str) -> bytes:
        """Fetch an object's bytes. Raises KeyError if absent."""
        ...

    def head(self, key: str) -> Obj | None:
        """Object metadata, or None if the key does not exist."""
        ...

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
        *,
        allow_media: bool = False,
    ) -> None: ...

    def delete(self, key: str, *, allow_media: bool = False) -> None: ...


class GuardedBucket:
    """Mixin supplying the media guard. Backends call `_guard` before writing."""

    readonly: bool = True

    def _guard(self, key: str, allow_media: bool) -> None:
        if self.readonly:
            raise ReadOnlyBucket(
                f"bucket is open read-only; refusing to write {key!r}. "
                "Phase 1 of this tool never writes."
            )
        if not allow_media and not is_writable_key(key):
            raise MediaWriteRefused(
                f"{key!r} is a media file. This tool does not create, overwrite, "
                "or delete media. Only index.json, sidecars, and thumbnails are "
                "writable."
            )
