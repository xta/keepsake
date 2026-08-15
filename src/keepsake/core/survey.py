"""What is actually in this bucket, and what would adopting it involve.

A bucket that has never seen keepsake classifies as 100% unindexed media, which
is correct but says nothing useful. The survey is the report that does: what
file types are here, where they live, how big the library is, and what is
probably not media at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from keepsake.core.classify import Classification

VIDEO_EXTS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mpg", ".mpeg", ".wmv",
    ".3gp", ".webm", ".mts", ".m2ts", ".flv", ".ogv",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif", ".tiff"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".aiff"}

MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS | AUDIO_EXTS


def extension_of(key: str) -> str:
    base = key.rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].lower()


@dataclass
class Bucketed:
    count: int = 0
    bytes: int = 0

    def add(self, size: int) -> None:
        self.count += 1
        self.bytes += size


@dataclass
class Survey:
    total_objects: int = 0
    total_bytes: int = 0
    by_extension: dict[str, Bucketed] = field(default_factory=dict)
    by_prefix: dict[str, Bucketed] = field(default_factory=dict)
    #: keys whose extension is not recognised as media -- candidates for the
    #: "keepsake buckets hold a keepsake library and nothing else" rule.
    non_media: list[str] = field(default_factory=list)
    non_media_bytes: int = 0
    sidecars_present: int = 0
    sidecars_needed: int = 0
    index_present: bool = False


def survey(result: Classification, *, prefix_depth: int = 1) -> Survey:
    out = Survey(index_present=result.index_present)
    out.sidecars_present = len(result.media)
    out.sidecars_needed = len(result.unindexed)

    by_ext: dict[str, Bucketed] = defaultdict(Bucketed)
    by_prefix: dict[str, Bucketed] = defaultdict(Bucketed)

    for key, obj in result.objects.items():
        out.total_objects += 1
        out.total_bytes += obj.size

        ext = extension_of(key)
        by_ext[ext or "(none)"].add(obj.size)

        parts = key.split("/")
        prefix = "/".join(parts[:prefix_depth]) + "/" if len(parts) > prefix_depth else "(root)"
        by_prefix[prefix].add(obj.size)

        # Sidecars and thumbnails are companions, not stray files.
        if key in result.media.values() or key in result.thumbnails.values():
            continue
        if ext not in MEDIA_EXTS:
            out.non_media.append(key)
            out.non_media_bytes += obj.size

    out.by_extension = dict(sorted(by_ext.items(), key=lambda kv: -kv[1].bytes))
    out.by_prefix = dict(sorted(by_prefix.items(), key=lambda kv: -kv[1].bytes))
    out.non_media.sort()
    return out


def human_bytes(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < step or unit == "TB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:,.1f} TB"


def human_duration(seconds: float | int | None) -> str:
    """`3:42` or `1:02:13`. Empty when the runtime is unknown."""
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def compact_bytes(n: int) -> str:
    """`62 MB`, `1.2 GB` -- rounded harder than human_bytes, for list columns."""
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < step or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.0f} {unit}" if value >= 10 else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.0f} TB"
