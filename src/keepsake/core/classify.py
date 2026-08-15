"""The classification pass from SPEC.md "Reindexing".

Order is load-bearing. Sidecars establish the known media set first; only then
can a `.jpg` be told apart from standalone media that happens to be an image.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from keepsake.storage.base import INDEX_KEY, Obj, split_companion


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
    #: media key -> the competing companion keys claiming it. SPEC.md: report
    #: the ambiguity rather than choosing one.
    ambiguous: dict[str, list[str]] = field(default_factory=dict)
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

    # 1. Sidecars. Every remaining key whose suffix is `.json` (in any case) is
    #    a sidecar; stripping the suffix yields the media key it describes.
    #    This establishes the known media set.
    claimed: dict[str, list[str]] = defaultdict(list)
    sidecar_keys: set[str] = set()
    for key in keys:
        split = split_companion(key)
        if split and split[1] == "sidecar":
            claimed[split[0]].append(key)
            sidecar_keys.add(key)

    present = keys - sidecar_keys

    for media, sidecars in claimed.items():
        if media not in present:
            result.orphan_sidecars.extend(sidecars)
        elif len(sidecars) > 1:
            result.ambiguous[media] = sorted(sidecars)
        else:
            result.media[media] = sidecars[0]
    result.orphan_sidecars.sort()

    # 2. Thumbnails. A key formed by appending an image extension to a key in
    #    the known media set is that file's thumbnail.
    remaining = present - set(result.media)
    thumbs: dict[str, list[str]] = defaultdict(list)
    thumb_keys: set[str] = set()
    for key in remaining:
        split = split_companion(key)
        if split and split[1] == "thumbnail" and split[0] in result.media:
            thumbs[split[0]].append(key)
            thumb_keys.add(key)

    for media, candidates in thumbs.items():
        if len(candidates) > 1:
            result.ambiguous.setdefault(media, []).extend(sorted(candidates))
        else:
            result.thumbnails[media] = candidates[0]

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
        split = split_companion(key)
        if split and split[1] == "thumbnail" and split[0] in unindexed:
            suspects[split[0]] = key
    return suspects
