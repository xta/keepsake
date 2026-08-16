"""Put a local file into a library.

Kept out of both front ends, the way `tui/library.py` keeps the editing logic
out of the Textual app, so preflight and write order can be tested without a
terminal and without a network.

Two ideas run through this file:

**Refuse early, in the plan.** Every reason an upload cannot happen is found
before a byte moves and reported next to the files that *can*, so a bad file in
a batch of twenty costs you a line of output rather than a half-finished
transfer. `Candidate.problem` carries the reason; nothing raises.

**The sidecar is still the commit marker.** Media goes up first, its sidecar
second. Dying in between leaves media with no sidecar -- a state `check`
already reports and `sync` already repairs -- rather than a sidecar describing
a file that never arrived.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from keepsake.core.adopt import guess_media_type, rfc3339, sidecar_payload
from keepsake.core.moov import read_movie_header_at
from keepsake.storage.base import (
    MAX_SINGLE_PUT,
    SIDECAR_SUFFIX,
    Bucket,
    has_extension,
    is_writable_key,
)

#: Read size for hashing. Big enough that a 3 GB file is a few thousand reads.
CHUNK = 1024 * 1024


class PrefixError(ValueError):
    """Raised for a destination prefix that cannot be used as one."""


def normalize_prefix(into: str | None) -> str | None:
    """Turn a typed destination into a key prefix.

    Three outcomes, and the distinction between the first two is the whole
    point:

    - `None` or empty -> `None`, meaning "use the dated layout". Leaving the
      field alone must never be the thing that drops files at the bucket root.
    - `"/"` -> `""`, the bucket root. Reachable only by asking for it.
    - anything else -> that prefix with exactly one trailing slash.
    """
    if into is None:
        return None
    text = into.strip()
    if not text:
        return None
    if text == "/":
        return ""

    segments = [part for part in text.strip("/").split("/") if part]
    if not segments:
        return ""
    for segment in segments:
        if segment in (".", ".."):
            raise PrefixError(
                f"{into!r} contains {segment!r}. A key prefix is a literal path, "
                "not a relative one."
            )
    return "/".join(segments) + "/"


def dated_prefix(recorded_at: str | None, now: datetime | None = None) -> str:
    """`YYYY/MM/` -- the layout PhotoSync already writes into these buckets.

    From the recording date when the file's own header supplied one, so a tape
    digitised today is filed under the year it was shot. From today otherwise,
    which is a guess, but a visible one: it appears in the plan before anything
    is written, and `--into` overrides it.
    """
    if recorded_at and len(recorded_at) >= 7:
        year, month = recorded_at[:4], recorded_at[5:7]
        if year.isdigit() and month.isdigit():
            return f"{year}/{month}/"
    moment = now or datetime.now(timezone.utc)
    return f"{moment.year:04d}/{moment.month:02d}/"


@dataclass
class Candidate:
    """One file, and everything decided about it before the upload starts."""

    path: Path
    key: str
    size: int
    media_type: str | None = None
    recorded_at: str | None = None
    duration_s: float | None = None
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def sidecar_key(self) -> str:
        return self.key + SIDECAR_SUFFIX


def parse_paths(text: str) -> list[Path]:
    """Paths from a line of typed or dragged-in text.

    Dragging files from Finder into a terminal pastes them shell-quoted, so
    `shlex` is not a flourish -- it is what makes drag-and-drop work for a path
    containing a space. Globs and `~` are expanded because anyone typing a path
    into a box expects the things the shell does.
    """
    try:
        tokens = shlex.split(text)
    except ValueError:
        # An unbalanced quote mid-typing. Fall back to whitespace splitting so
        # the live preview keeps working while someone is still typing.
        tokens = text.split()

    found: list[Path] = []
    for token in tokens:
        expanded = Path(token).expanduser()
        if any(char in token for char in "*?["):
            matches = sorted(expanded.parent.glob(expanded.name))
        else:
            matches = [expanded]
        for match in matches:
            if match not in found:
                found.append(match)
    return found


def hash_file(path: Path, progress: Callable[[int], None] | None = None) -> str:
    """SHA-256 of a file, in its own pass.

    Deliberately not folded into the upload as a wrapping reader: the body
    handed to boto3 has to stay plainly seekable so a retry can rewind it. A
    second local read costs a few seconds now; computing this later would mean
    downloading the whole file back.
    """
    digest = hashlib.sha256()
    seen = 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
            seen += len(chunk)
            if progress is not None:
                progress(seen)
    return digest.hexdigest()


def _existing_keys(bucket: Bucket, prefix: str, cache: dict[str, set[str]]) -> set[str]:
    if prefix not in cache:
        cache[prefix] = {obj.key for obj in bucket.list(prefix)}
    return cache[prefix]


def plan_uploads(
    paths: Sequence[Path],
    bucket: Bucket,
    *,
    into: str | None = None,
    as_name: str | None = None,
    now: datetime | None = None,
) -> list[Candidate]:
    """Work out where each file would land, and what would stop it.

    Every check happens here rather than at write time, so the plan shown to a
    human is the whole truth about what is about to happen.
    """
    prefix = normalize_prefix(into)
    listings: dict[str, set[str]] = {}
    taken: dict[str, Path] = {}
    candidates: list[Candidate] = []

    for path in paths:
        path = Path(path).expanduser()
        if not path.exists():
            candidates.append(Candidate(path, "", 0, problem="no such file"))
            continue
        if not path.is_file():
            candidates.append(Candidate(path, "", 0, problem="not a regular file"))
            continue

        size = path.stat().st_size
        name = as_name or path.name

        # SPEC.md requires every media key to carry an extension naming its
        # format. A file without one cannot be catalogued, so refusing here is
        # kinder than uploading something the library will never show.
        if not has_extension(name):
            candidates.append(
                Candidate(
                    path,
                    "",
                    size,
                    problem="no file extension. SPEC requires one naming the format "
                    "(.mov, .mp4, .jpg); rename it or pass --as",
                )
            )
            continue

        header = read_movie_header_at(path)
        recorded_at = header.recorded_at if header else None
        duration_s = header.duration_s if header else None
        key = (prefix if prefix is not None else dated_prefix(recorded_at, now)) + name

        candidate = Candidate(
            path=path,
            key=key,
            size=size,
            media_type=guess_media_type(name),
            recorded_at=recorded_at,
            duration_s=duration_s,
        )

        candidate.problem = _problem_with(candidate, bucket, listings, taken)
        if candidate.ok:
            taken[key] = path
        candidates.append(candidate)

    return candidates


def _problem_with(
    candidate: Candidate,
    bucket: Bucket,
    listings: dict[str, set[str]],
    taken: dict[str, Path],
) -> str | None:
    key, size = candidate.key, candidate.size

    if size > MAX_SINGLE_PUT:
        return (
            f"{size / 1024**3:.1f} GB, over the {MAX_SINGLE_PUT / 1024**3:.0f} GB "
            "single-upload limit. keepsake uploads in one request, so this file "
            "cannot be sent as-is -- split or transcode it first"
        )
    if size == 0:
        return "empty file"

    # A key shaped like a companion would be read as another file's sidecar or
    # thumbnail, and the media itself would never be catalogued.
    if is_writable_key(key):
        return (
            f"{key} is shaped like a companion key, so the library would read it "
            "as another file's sidecar or thumbnail rather than as media"
        )

    if key in taken:
        return f"another file in this batch already claims {key} ({taken[key]})"

    if bucket.head(key) is not None:
        return f"{key} already exists. keepsake never overwrites media; pass --as to rename"

    # SPEC.md forbids a library from holding two keys differing only in case:
    # object storage keeps both, but copying to macOS or Windows collapses one
    # onto the other. `head` cannot see this, so the prefix has to be listed.
    prefix = key.rsplit("/", 1)[0] + "/" if "/" in key else ""
    for existing in _existing_keys(bucket, prefix, listings):
        if existing != key and existing.lower() == key.lower():
            return (
                f"{existing} differs from {key} only in case. Object storage keeps "
                "both, but copying the library to macOS or Windows would collapse "
                "one onto the other"
            )
    return None


def upload_one(
    bucket: Bucket,
    candidate: Candidate,
    *,
    new_id: Callable[[], str],
    title: str | None = None,
    progress: Callable[[int], None] | None = None,
    now: datetime | None = None,
) -> str:
    """Upload one file and write its sidecar. Returns the media key.

    SPEC.md's write order, and the reason for it: the sidecar goes last because
    it is the commit marker, so it can never describe a file that is not there.
    """
    digest = hash_file(candidate.path)

    with candidate.path.open("rb") as fh:
        bucket.put_media(
            candidate.key,
            fh,
            candidate.media_type,
            size=candidate.size,
            progress=progress,
        )

    payload = sidecar_payload(
        filename=candidate.key.rsplit("/", 1)[-1],
        new_id=new_id(),
        uploaded_at=rfc3339(now or datetime.now(timezone.utc)),
        size_bytes=candidate.size,
        media_type=candidate.media_type,
        title=title,
        recorded_at=candidate.recorded_at,
        duration_s=candidate.duration_s,
        sha256=digest,
    )
    bucket.put(
        candidate.sidecar_key,
        json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )
    return candidate.key


def upload_all(
    bucket: Bucket,
    candidates: Iterable[Candidate],
    *,
    new_id: Callable[[], str],
    title: str | None = None,
    on_start: Callable[[Candidate], None] | None = None,
    progress: Callable[[Candidate, int], None] | None = None,
) -> tuple[list[str], list[tuple[Candidate, str]]]:
    """Upload every viable candidate. Returns the keys written and the failures.

    One file failing does not abort the rest, for the same reason a failed
    sidecar write does not abort `adopt.apply`: each upload is an independent
    commit, so a partial batch is a safe state the tool already understands.
    """
    written: list[str] = []
    failures: list[tuple[Candidate, str]] = []
    for candidate in candidates:
        if not candidate.ok:
            continue
        if on_start is not None:
            on_start(candidate)
        try:
            written.append(
                upload_one(
                    bucket,
                    candidate,
                    new_id=new_id,
                    title=title,
                    progress=(
                        (lambda seen, c=candidate: progress(c, seen))
                        if progress is not None
                        else None
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported verbatim to the caller
            failures.append((candidate, f"{type(exc).__name__}: {exc}"))
    return written, failures
