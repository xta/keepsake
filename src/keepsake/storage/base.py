"""Storage abstraction and the media-write guard.

Every bucket backend implements `Bucket`. The point of the abstraction is not
provider portability (only Backblaze B2 is targeted today) but testability: the
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
from typing import Iterator, Literal, Protocol, runtime_checkable

# The one reserved key (SPEC.md "Reserved key"). A nested index.json is an
# ordinary sidecar, not this.
INDEX_KEY = "index.json"

SIDECAR_SUFFIX = ".json"

# Exactly the extensions SPEC.md names. Deliberately excludes ".jpeg" -- adding
# it here would be a silent divergence from our own spec.
THUMB_EXTS = (".jpg", ".png", ".webp")

CompanionKind = Literal["sidecar", "thumbnail"]


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


def has_extension(key: str) -> bool:
    """True when `key` can name media, by SPEC.md's extension rule.

    SPEC.md: "A key is media only when its final path segment does not begin
    with `.` and contains a `.`." The leading-dot clause is load-bearing --
    it keeps B2's own `.bzEmpty` folder placeholders and macOS `.DS_Store`
    out of the library without maintaining a list of junk filenames.
    """
    base = key.rsplit("/", 1)[-1]
    return not base.startswith(".") and "." in base


def split_companion(key: str) -> tuple[str, CompanionKind] | None:
    """Split a companion key into the media key it describes and its kind.

    SPEC.md: companion suffixes match case-insensitively, but the media portion
    of the key matches exactly, because object storage keys are case-sensitive
    and `clip.mov` and `clip.MOV` are genuinely different files.

    Returns None for keys that are not companions.
    """
    lowered = key.lower()

    if lowered.endswith(SIDECAR_SUFFIX):
        media = key[: -len(SIDECAR_SUFFIX)]
        return (media, "sidecar") if media else None

    for ext in THUMB_EXTS:
        if lowered.endswith(ext):
            media = key[: -len(ext)]
            # `piano.mp4.jpg` -> `piano.mp4`, which still carries an extension,
            # so it plausibly names a media file. `vacation.jpg` -> `vacation`,
            # which does not, so that key is standalone media.
            if media and has_extension(media):
                return media, "thumbnail"
            return None
    return None


def is_writable_key(key: str) -> bool:
    """True if `key` is something this tool is allowed to create or replace.

    Conservative by design: it recognises the *shape* of a companion key
    without consulting the bucket. Callers holding a Classification should
    prefer its exact `media`/`thumbnails` maps; this is the backstop for
    callers that do not.
    """
    if key == INDEX_KEY:
        return True
    return split_companion(key) is not None


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
                f"bucket is open read-only; refusing to write {key!r}."
            )
        if not allow_media and not is_writable_key(key):
            raise MediaWriteRefused(
                f"{key!r} is a media file. This tool does not create, overwrite, "
                "or delete media. Only index.json, sidecars, and thumbnails are "
                "writable."
            )
