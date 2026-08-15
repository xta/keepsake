"""A bucket backed by a local directory. Used by the test suite.

Keys map to relative paths, so a fixture bucket is just a directory tree you
can read in a diff. No network, no credentials, no B2 quirks.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from keepsake.storage.base import GuardedBucket, Obj


class LocalDirBucket(GuardedBucket):
    def __init__(self, root: Path | str, *, name: str = "local", readonly: bool = True):
        self.root = Path(root)
        self.name = name
        self.readonly = readonly

    def list(self, prefix: str = "") -> Iterator[Obj]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(self.root).as_posix()
            if not key.startswith(prefix):
                continue
            stat = path.stat()
            yield Obj(
                key=key,
                size=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )

    def _path(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def head(self, key: str) -> Obj | None:
        path = self._path(key)
        if not path.is_file():
            return None
        stat = path.stat()
        return Obj(
            key=key,
            size=stat.st_size,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
        *,
        allow_media: bool = False,
    ) -> None:
        self._guard(key, allow_media)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, key: str, *, allow_media: bool = False) -> None:
        self._guard(key, allow_media)
        self._path(key).unlink(missing_ok=True)

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self._path(key).as_uri()

    def seed(self, key: str, data: bytes = b"") -> None:
        """Write a key bypassing the guard. Tests only -- builds fixture media."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
