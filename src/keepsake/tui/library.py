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
from keepsake.storage.base import Bucket

#: A named library: the profile it came from and the bucket holding it.
Source = tuple[str, Bucket]

#: The fields a human fills in. Everything else in a sidecar is machine fact.
EDITABLE = ("title", "recorded_at", "tags", "location", "notes")

#: Stored as a JSON array, edited as comma-separated text.
LIST_FIELDS = frozenset({"tags"})


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


def load_items(sources: Sequence[Source], prefix: str = "") -> list[Item]:
    """Every media file with a readable sidecar, across every open library.

    Sorted by profile then key, so one library's videos stay together.
    """
    items: list[Item] = []
    for profile, bucket in sources:
        result = classify(bucket.list(prefix))
        for media_key, sidecar_key in sorted(result.media.items()):
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
                )
            )
    return items


def save_item(item: Item) -> None:
    """Write the sidecar, merging this session's edits onto its current state.

    SPEC.md's concurrency note: sidecar writes are last-writer-wins, and the
    unsafe window is the whole edit session, not the request. Someone typing a
    title for two minutes and then PUTting the object they loaded at startup
    would silently discard anything written in between.

    So the stored sidecar is re-read here and only the fields edited in this
    session are applied. That narrows the window to a single request. B2's
    S3 API has no conditional writes, so it cannot be closed entirely.
    """
    if not item.changed:
        return

    bucket = item.bucket
    try:
        stored = json.loads(bucket.get(item.sidecar_key))
        if not isinstance(stored, dict):
            stored = dict(item.payload)
    except (KeyError, json.JSONDecodeError):
        stored = dict(item.payload)

    for name in item.changed:
        if name in item.payload:
            stored[name] = item.payload[name]
        else:
            stored.pop(name, None)

    bucket.put(
        item.sidecar_key,
        json.dumps(stored, indent=2, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
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
