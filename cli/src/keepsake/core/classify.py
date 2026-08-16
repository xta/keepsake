"""The classification pass from SPEC.md "Reindexing".

Each step reads the set of keys present, not the results of the step before it.
Classification describes what each key *is*, not whether its item is complete:
a thumbnail is recognised as a thumbnail before its media has a sidecar, so a
bucket freshly filled by an upload tool does not count derived files as library
items. The media itself stays unindexed until its sidecar is written.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from keepsake.storage.base import INDEX_KEY, Obj, has_extension, split_companion


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
    #: keys that are not media by SPEC.md's extension rule. Not part of the
    #: library and never catalogued, but reported so they stay visible.
    ignored: list[str] = field(default_factory=list)
    #: lowercased key -> the keys colliding on it. SPEC.md forbids a library
    #: from holding two keys that differ only in case.
    case_collisions: dict[str, list[str]] = field(default_factory=dict)
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

    # SPEC.md: "A key that is not media by the rule above is not part of the
    # library." Filtering here rather than at the end keeps every later step
    # from having to restate the rule.
    keys = {key for key in result.objects if has_extension(key)}
    result.ignored = sorted(set(result.objects) - keys)

    # SPEC.md: a library must not contain two keys differing only in case.
    # Object storage allows it; no filesystem the archive is likely to be
    # copied to can represent both, so report rather than resolve.
    lowered: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        lowered[key.lower()].append(key)
    result.case_collisions = {
        low: sorted(group) for low, group in lowered.items() if len(group) > 1
    }

    # 1. Sidecars. Every remaining key whose suffix is `.json` (in any case) is
    #    a sidecar; stripping the suffix yields the media key it describes.
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

    # 2. Thumbnails. A key formed by appending an image extension to another
    #    key present in the bucket is that key's thumbnail -- whether or not
    #    the media has a sidecar yet.
    remaining = present - set(result.media)
    thumbs: dict[str, list[str]] = defaultdict(list)
    thumb_keys: set[str] = set()
    for key in remaining:
        split = split_companion(key)
        if split and split[1] == "thumbnail" and split[0] in present:
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
