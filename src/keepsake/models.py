"""Sidecar and index models.

`extra="allow"` is not incidental -- SPEC.md requires that a writer which does
not recognise a field carries it through unchanged, so clients of different
versions can coexist. Pydantic gives us that for free as long as we never
construct a sidecar from scratch when round-tripping one we read.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


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
