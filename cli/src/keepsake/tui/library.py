"""The editable view of a library: load sidecars, edit fields, write them back.

Separated from the Textual app so the interesting logic -- especially the
merge-on-save -- is testable without driving a terminal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from keepsake.core.classify import classify
from keepsake.core.sidecar import merge_sidecar
from keepsake.storage.base import Bucket

#: A named library: the profile it came from and the bucket holding it.
Source = tuple[str, Bucket]

#: The fields a human fills in. Everything else in a sidecar is machine fact.
EDITABLE = ("title", "recorded_at", "tags", "location", "notes")

#: Stored as a JSON array, edited as comma-separated text.
LIST_FIELDS = frozenset({"tags"})

#: Shown beside each field and as its placeholder. A field with a required
#: shape has to say so -- otherwise people reasonably type dates the way they
#: write dates, and the sidecar ends up off-spec.
FIELD_HINTS = {
    "recorded_at": "YYYY-MM-DD",
    "tags": "comma, separated",
}

#: SPEC.md: `YYYY-MM-DD`, or RFC 3339 when the time is known.
RECORDED_AT_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?$"
)


def is_spec_date(text: str) -> bool:
    """True when `text` is empty or matches SPEC's recorded_at format."""
    import re

    return not text.strip() or bool(re.match(RECORDED_AT_PATTERN, text.strip()))


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _from_text(name: str, text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if name in LIST_FIELDS:
        parsed = [part.strip() for part in text.split(",")]
        return [part for part in parsed if part] or None
    return text


@dataclass
class Item:
    #: Which library this came from. Several can be open at once, so an item
    #: has to carry its own bucket -- a save must go back where it came from.
    profile: str
    bucket: Bucket
    media_key: str
    sidecar_key: str
    payload: dict[str, Any]
    size: int
    #: The thumbnail's own key, from classification rather than from the
    #: sidecar's `thumbnail` field. The field is advisory and can be stale or
    #: absent; this is what is actually in the bucket. None when there is none.
    thumbnail_key: str | None = None
    #: Fields edited this session. Only these are merged on save, so a field
    #: someone else changed meanwhile is not clobbered.
    changed: set[str] = field(default_factory=set)
    #: The payload as last read or written, so an edit that is typed and then
    #: undone stops counting as a change.
    original: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.original:
            self.original = dict(self.payload)

    @property
    def dirty(self) -> bool:
        return bool(self.changed)

    @property
    def name(self) -> str:
        return self.media_key.rsplit("/", 1)[-1]

    @property
    def uid(self) -> str:
        """Unique across libraries -- two buckets can hold the same key."""
        return f"{self.profile}\x00{self.media_key}"

    def text(self, name: str) -> str:
        return _to_text(self.payload.get(name))

    def edit(self, name: str, text: str) -> None:
        """Stage an edit. No network until `save`."""
        value = _from_text(name, text)
        if value is None:
            self.payload.pop(name, None)
        else:
            self.payload[name] = value
        # Compared against the value this session started from, not the running
        # payload -- otherwise typing a title and then restoring the original
        # would still count as a pending change.
        if value == self.original.get(name):
            self.changed.discard(name)
        else:
            self.changed.add(name)


def load_items(
    sources: Sequence[Source],
    prefix: str = "",
    only: set[str] | None = None,
) -> list[Item]:
    """Every media file with a readable sidecar, across every open library.

    Sorted by profile then key, so one library's videos stay together.

    `only` narrows the list to specific media keys, which is what `keepsake
    add` opens the editor with: after uploading four files you want to title
    those four, not scroll a library of hundreds looking for them.
    """
    items: list[Item] = []
    for profile, bucket in sources:
        result = classify(bucket.list(prefix))
        for media_key, sidecar_key in sorted(result.media.items()):
            if only is not None and media_key not in only:
                continue
            try:
                payload = json.loads(bucket.get(sidecar_key))
            except (KeyError, json.JSONDecodeError):
                continue  # `keepsake status` reports these
            if not isinstance(payload, dict):
                continue
            items.append(
                Item(
                    profile=profile,
                    bucket=bucket,
                    media_key=media_key,
                    sidecar_key=sidecar_key,
                    payload=payload,
                    size=result.size_of(media_key),
                    thumbnail_key=result.thumbnails.get(media_key),
                )
            )
    return items


def load_thumbnail(item: Item) -> bytes | None:
    """The thumbnail's bytes, or None when there is none or it will not read.

    A thumbnail is derived and disposable, so failing to fetch one is never
    worth surfacing as an error -- the pane just stays empty.
    """
    if item.thumbnail_key is None:
        return None
    try:
        return item.bucket.get(item.thumbnail_key)
    except Exception:  # noqa: BLE001 - an absent preview is not a failure
        return None


def save_item(item: Item) -> None:
    """Write the sidecar, merging this session's edits onto its current state.

    Only the fields edited in this session are applied, so a field somebody
    else changed meanwhile survives. `merge_sidecar` carries the rest of the
    rule -- see `core/sidecar.py` for why re-reading here matters.

    The fallback is this item's own payload: a sidecar that has become
    unreadable since it was loaded should not cost someone the title they just
    typed, and the copy loaded at startup is the best remaining record of what
    the file said.
    """
    if not item.changed:
        return

    # A field in `changed` but absent from the payload was cleared, and
    # `merge_sidecar` reads None as "remove this".
    fields = {name: item.payload.get(name) for name in item.changed}
    stored = merge_sidecar(
        item.bucket, item.sidecar_key, fields, fallback=dict(item.payload)
    )

    item.payload = stored
    item.original = dict(stored)
    item.changed.clear()


def titled(items: Iterable[Item]) -> int:
    return sum(1 for item in items if item.text("title"))


def open_externally(url: str) -> None:
    """Hand a URL to the system's default application."""
    if sys.platform == "darwin":
        command = ["open", url]
    elif sys.platform.startswith("linux"):
        command = ["xdg-open", url]
    elif sys.platform == "win32":  # pragma: no cover
        command = ["cmd", "/c", "start", "", url]
    else:  # pragma: no cover
        raise RuntimeError(f"no known opener for {sys.platform}")
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
