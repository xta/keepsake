"""Storage abstraction and the media-write guard.

Every bucket backend implements `Bucket`. The point of the abstraction is not
provider portability (only Backblaze B2 is targeted today) but testability: the
whole test suite runs against `LocalDirBucket` with no network and no creds.

Safety rule enforced here, at one chokepoint:

    This tool may create new media, and may never overwrite or delete it.
    Everything else it writes is one of exactly three kinds of key -- the root
    index.json, `{media}.json` sidecars, and `{media}.{jpg,png,webp}`
    thumbnails.

`put` and `delete` refuse media outright unless the caller passes
`allow_media=True`, which only an explicit user-invoked delete command sets.
`put_media` is the one door to a media key, and it opens in one direction: it
writes only where nothing exists, so a filename collision is an error rather
than a silent loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Callable, Iterator, Literal, Protocol, runtime_checkable

# The one reserved key (SPEC.md "Reserved key"). A nested index.json is an
# ordinary sidecar, not this.
INDEX_KEY = "index.json"

SIDECAR_SUFFIX = ".json"

# Exactly the extensions SPEC.md names. Deliberately excludes ".jpeg" -- adding
# it here would be a silent divergence from our own spec.
THUMB_EXTS = (".jpg", ".png", ".webp")

CompanionKind = Literal["sidecar", "thumbnail"]

#: A single-request PUT tops out at 5 GB on B2 and on S3 itself. Lifting it
#: means multipart, which means s3transfer, which has a checksum bug against B2
#: (see storage/b2.py). We refuse instead, before a byte moves.
MAX_SINGLE_PUT = 5 * 1024**3


@dataclass(frozen=True)
class Obj:
    """One object in a bucket, as returned by a listing."""

    key: str
    size: int
    last_modified: datetime | None = None
    etag: str | None = None


class MediaWriteRefused(Exception):
    """Raised when something tries to write or delete a media file."""


class MediaExists(MediaWriteRefused):
    """Raised when an upload would land on a key that already holds something.

    A subclass of MediaWriteRefused so callers that already treat the guard as
    a single category keep working: this is still the guard saying no.
    """


class MediaTooLarge(Exception):
    """Raised when a file exceeds what a single-request PUT can carry."""


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


class ProgressReader:
    """Wraps a file object, reporting how many bytes have been read.

    A 300 MB upload with no feedback is indistinguishable from a hang, and
    neither backend offers a progress hook: boto3's callback lives on the
    managed `upload_fileobj` path we deliberately avoid. Counting reads works
    for any consumer of a file object, so the CLI's bar and the TUI's bar are
    fed by the same object.
    """

    def __init__(self, fh: BinaryIO, on_read: Callable[[int], None] | None = None):
        self._fh = fh
        self._on_read = on_read
        self.seen = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(size)
        self.seen += len(chunk)
        if self._on_read is not None:
            self._on_read(self.seen)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        # botocore rewinds the body before retrying a request. The count has to
        # rewind with it, or a retried upload reports 150% complete.
        position = self._fh.seek(offset, whence)
        if offset == 0 and whence == 0:
            self.seen = 0
            if self._on_read is not None:
                self._on_read(0)
        return position

    def tell(self) -> int:
        return self._fh.tell()


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

    def put_media(
        self,
        key: str,
        source: BinaryIO,
        content_type: str | None = None,
        *,
        size: int,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        """Stream a new media file to `key`. Never overwrites."""
        ...

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
                f"{key!r} is a media file. This tool does not overwrite or delete "
                "media. Only index.json, sidecars, and thumbnails are writable "
                "here; new media goes through put_media."
            )

    def _guard_media_create(self, key: str, size: int) -> None:
        """The one path to a media key: create, never replace.

        Callers are expected to have run their own preflight and reported the
        problem in context. This is the backstop, so that the invariant holds
        for any caller rather than for the careful ones.
        """
        if self.readonly:
            raise ReadOnlyBucket(
                f"bucket is open read-only; refusing to write {key!r}."
            )
        if not has_extension(key):
            raise MediaWriteRefused(
                f"{key!r} has no file extension. SPEC.md requires every media key "
                "to carry one naming its format, and a key without one is never "
                "catalogued."
            )
        if is_writable_key(key):
            raise MediaWriteRefused(
                f"{key!r} is shaped like a companion key, so the library would read "
                "it as another file's sidecar or thumbnail rather than as media."
            )
        if size > MAX_SINGLE_PUT:
            raise MediaTooLarge(
                f"{key!r} is {size / 1024**3:.1f} GB, over the "
                f"{MAX_SINGLE_PUT / 1024**3:.0f} GB single-upload limit."
            )
        if self.head(key) is not None:  # type: ignore[attr-defined]
            raise MediaExists(
                f"{key!r} already exists. This tool never overwrites media; "
                "rename the file or choose another destination."
            )
