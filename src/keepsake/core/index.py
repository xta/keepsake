"""Build the derived catalog described in SPEC.md "index.json".

Phase 1 builds it in memory only. Nothing here writes to a bucket.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from keepsake.core.classify import Classification
from keepsake.storage.base import Bucket


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_index(
    result: Classification,
    bucket: Bucket,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Inline every sidecar, keyed by the media file's full path from the root.

    `items` is sorted by `path` ascending. SPEC.md calls this a stability
    guarantee rather than a display order: it keeps regenerated indexes
    byte-stable and cacheable across rebuilds.
    """
    items: list[dict[str, Any]] = []
    for media_key, sidecar_key in result.media.items():
        try:
            data = json.loads(bucket.get(sidecar_key))
        except (KeyError, json.JSONDecodeError):
            # `check` reports these; the index simply omits them.
            continue
        if not isinstance(data, dict):
            continue
        items.append({"path": media_key, **data})

    items.sort(key=lambda entry: entry["path"])
    return {
        "generated_at": generated_at or now_rfc3339(),
        "count": len(items),
        "items": items,
    }


def serialize(index: dict[str, Any]) -> bytes:
    return json.dumps(index, indent=2, ensure_ascii=False).encode("utf-8")
