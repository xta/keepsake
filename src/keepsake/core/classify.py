"""The classification pass from SPEC.md "Reindexing".

Order is load-bearing. Sidecars establish the known media set first; only then
can a `.jpg` be told apart from standalone media that happens to be an image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from keepsake.storage.base import INDEX_KEY, SIDECAR_SUFFIX, THUMB_EXTS, Obj


@dataclass
class Classification:
    objects: dict[str, Obj] = field(default_factory=dict)
    #: media key -> its sidecar key
    media: dict[str, str] = field(default_factory=dict)
    #: media key -> its thumbnail key
    thumbnails: dict[str, str] = field(default_factory=dict)
    #: media present with no sidecar. Expected state, surfaced not hidden.
    unindexed: list[str] = field(default_factory=list)
    #: sidecar whose media key is absent. Should be unreachable under the
    #: documented write order; report, do not index.
    orphan_sidecars: list[str] = field(default_factory=list)
    index_present: bool = False

    @property
    def total_objects(self) -> int:
        return len(self.objects)

    def size_of(self, key: str) -> int:
        obj = self.objects.get(key)
        return obj.size if obj else 0


def classify(objects: Iterable[Obj]) -> Classification:
    result = Classification()
    for obj in objects:
        if obj.key == INDEX_KEY:
            result.index_present = True
            continue
        result.objects[obj.key] = obj

    keys = set(result.objects)

    # 1. Sidecars. Every remaining `.json` key is a sidecar; stripping the
    #    suffix yields the media key it describes. This is the known media set.
    sidecars = {k for k in keys if k.endswith(SIDECAR_SUFFIX)}
    claimed = {k[: -len(SIDECAR_SUFFIX)]: k for k in sidecars}

    non_sidecars = keys - sidecars
    result.orphan_sidecars = sorted(
        sidecar for media, sidecar in claimed.items() if media not in non_sidecars
    )
    result.media = {
        media: sidecar for media, sidecar in claimed.items() if media in non_sidecars
    }

    # 2. Thumbnails. A key formed by appending an image extension to a key in
    #    the known media set is that file's thumbnail.
    remaining = non_sidecars - set(result.media)
    thumb_keys: set[str] = set()
    for key in remaining:
        for ext in THUMB_EXTS:
            if key.endswith(ext) and key[: -len(ext)] in result.media:
                result.thumbnails[key[: -len(ext)]] = key
                thumb_keys.add(key)
                break

    # 3. Everything left is media with no sidecar, and is unindexed.
    result.unindexed = sorted(remaining - thumb_keys)
    return result


def suspected_orphan_thumbnails(result: Classification) -> dict[str, str]:
    """Unindexed keys that look like thumbnails of other unindexed media.

    SPEC.md only recognises a thumbnail when its media file has a sidecar, so
    in a bucket with no sidecars yet, `clip.mp4.jpg` classifies as standalone
    media. That is the spec as written; this helper exists so `check` can say
    so out loud instead of silently miscounting the library.
    """
    unindexed = set(result.unindexed)
    suspects: dict[str, str] = {}
    for key in result.unindexed:
        for ext in THUMB_EXTS:
            if key.endswith(ext) and key[: -len(ext)] in unindexed:
                suspects[key[: -len(ext)]] = key
                break
    return suspects
