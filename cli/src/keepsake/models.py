"""Sidecar and index models.

`extra="allow"` is not incidental -- SPEC.md requires that a writer which does
not recognise a field carries it through unchanged, so clients of different
versions can coexist. Pydantic gives us that for free as long as we never
construct a sidecar from scratch when round-tripping one we read.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


def new_id() -> str:
    """A fresh sidecar `id`: UUID version 7, per RFC 9562.

    Hand-rolled because `uuid.uuid7` arrives in Python 3.14 and we target 3.11+.
    It is eight lines and the layout is fixed by the RFC, which beats taking a
    dependency for it -- and an archive meant to outlive its tools is better off
    resting on a published standard than on any one library.

    Time-ordered, though nothing here depends on that: SPEC.md treats `id` as
    opaque, and `index.json` sorts by path.
    """
    stamp = time.time_ns() // 1_000_000
    raw = bytearray(stamp.to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # variant 10xx
    return str(uuid.UUID(bytes=bytes(raw)))


class Sidecar(BaseModel):
    # The wire field is `schema`, but that name collides with an attribute on
    # BaseModel, so the Python attribute is `schema_version` and the alias
    # carries the real name in both directions.
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = Field(alias="schema")
    id: str
    file: str
    uploaded_at: str

    title: str | None = None
    recorded_at: str | None = None
    tags: list[str] | None = None
    location: str | None = None
    notes: str | None = None
    duration_s: float | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    sha256: str | None = None
    thumbnail: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """Serialise back to sidecar JSON, preserving unknown fields."""
        return self.model_dump(by_alias=True, exclude_none=True)


REQUIRED_SIDECAR_FIELDS = ("schema", "id", "file", "uploaded_at")
