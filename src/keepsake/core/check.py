"""Conformance and health checks against SPEC.md's failure-mode table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from keepsake.core.classify import Classification
from keepsake.core.survey import MEDIA_EXTS, extension_of
from keepsake.models import REQUIRED_SIDECAR_FIELDS, SCHEMA_VERSION
from keepsake.storage.base import SIDECAR_SUFFIX, Bucket

Level = Literal["error", "warn", "info"]


@dataclass
class Finding:
    level: Level
    code: str
    message: str
    key: str | None = None


def check(
    result: Classification,
    bucket: Bucket | None = None,
    *,
    read_sidecars: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []

    # SPEC: "Sidecar, no media" -- should be unreachable under the write order.
    for key in result.orphan_sidecars:
        findings.append(
            Finding(
                "error",
                "sidecar-no-media",
                f"sidecar describes a media file that is not in the bucket: "
                f"{key[: -len(SIDECAR_SUFFIX)]}",
                key,
            )
        )

    # SPEC: companions differing only in suffix case leave the library
    # ambiguous. Report rather than choosing one.
    for media, competing in sorted(result.ambiguous.items()):
        findings.append(
            Finding(
                "error",
                "ambiguous-companion",
                f"{media} is claimed by {len(competing)} competing companions "
                f"({', '.join(competing)}). Remove all but one.",
                media,
            )
        )

    # SPEC: "Media, no sidecar" -- expected, surfaced not hidden.
    if result.unindexed:
        findings.append(
            Finding(
                "info",
                "media-no-sidecar",
                f"{len(result.unindexed)} media file(s) have no sidecar and are "
                "unindexed. Run `keepsake sync` to generate stub sidecars.",
            )
        )

    # SPEC: "A library must not contain two keys differing only in case."
    # Companions competing on suffix case are already reported as ambiguous, so
    # exclude those groups rather than saying the same thing twice.
    already_reported = {key for group in result.ambiguous.values() for key in group}
    for _, group in sorted(result.case_collisions.items()):
        if set(group) <= already_reported:
            continue
        findings.append(
            Finding(
                "error",
                "case-collision",
                f"{len(group)} keys differ only in case ({', '.join(group)}). "
                "Object storage keeps both, but copying this library to macOS or "
                "Windows collapses one onto the other. Rename one.",
                group[0],
            )
        )

    # SPEC: a key that is not media by the extension rule is not part of the
    # library. Report it so it stays visible; do not catalogue it.
    if result.ignored:
        findings.append(
            Finding(
                "warn",
                "not-media",
                f"{len(result.ignored)} object(s) carry no file extension, or are "
                "dotfiles, so they are not part of the library and are not "
                "catalogued. Rename one with its correct extension to adopt it.",
            )
        )

    # SPEC: "Not a shared bucket."
    strays = [key for key in result.unindexed if extension_of(key) not in MEDIA_EXTS]
    if strays:
        findings.append(
            Finding(
                "warn",
                "non-media-present",
                f"{len(strays)} object(s) do not look like media and will not be "
                "adopted. A keepsake bucket should hold a keepsake library and "
                "nothing else; adopt them anyway with `sync --adopt-all`.",
            )
        )

    if not result.index_present:
        findings.append(
            Finding(
                "info",
                "no-index",
                "no index.json at the bucket root. Generate one with "
                "`keepsake sync --apply`.",
            )
        )

    if read_sidecars and bucket is not None:
        findings.extend(_check_sidecars(result, bucket))

    return findings


def _check_sidecars(result: Classification, bucket: Bucket) -> list[Finding]:
    findings: list[Finding] = []
    for media_key, sidecar_key in sorted(result.media.items()):
        try:
            raw = bucket.get(sidecar_key)
        except KeyError:
            continue
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            findings.append(
                Finding("error", "sidecar-invalid-json", f"not valid JSON: {exc}", sidecar_key)
            )
            continue
        if not isinstance(data, dict):
            findings.append(
                Finding("error", "sidecar-not-object", "sidecar is not a JSON object", sidecar_key)
            )
            continue

        missing = [f for f in REQUIRED_SIDECAR_FIELDS if f not in data]
        if missing:
            findings.append(
                Finding(
                    "error",
                    "sidecar-missing-fields",
                    f"missing required field(s): {', '.join(missing)}",
                    sidecar_key,
                )
            )

        schema = data.get("schema")
        if isinstance(schema, int) and schema > SCHEMA_VERSION:
            findings.append(
                Finding(
                    "warn",
                    "sidecar-future-schema",
                    f"schema {schema} is newer than this tool understands "
                    f"({SCHEMA_VERSION}); unknown fields will be preserved.",
                    sidecar_key,
                )
            )

        # SPEC "Key vs. contents": the key wins, `file` is advisory.
        expected = media_key.rsplit("/", 1)[-1]
        actual = data.get("file")
        if isinstance(actual, str) and actual != expected:
            findings.append(
                Finding(
                    "warn",
                    "sidecar-file-mismatch",
                    f"`file` is {actual!r} but the key implies {expected!r}. "
                    "The key wins; correct the sidecar.",
                    sidecar_key,
                )
            )
    return findings


def lifecycle_finding(bucket: Bucket) -> Finding | None:
    """B2 keeps every file version unless a lifecycle rule says otherwise."""
    checker = getattr(bucket, "lifecycle_keeps_all_versions", None)
    if checker is None:
        return None
    try:
        keeps_all = checker()
    except Exception as exc:  # pragma: no cover - network/permission dependent
        return Finding("info", "lifecycle-unknown", f"could not read lifecycle rules: {exc}")
    if keeps_all is None:
        return Finding(
            "info",
            "lifecycle-unknown",
            "the key lacks permission to read lifecycle rules; verify in the B2 UI "
            "that this bucket keeps only the last version of a file.",
        )
    if keeps_all:
        return Finding(
            "warn",
            "lifecycle-keeps-all-versions",
            "this bucket retains every file version. Sidecars are rewritten on "
            "every metadata edit, so this accumulates billable JSON revisions. "
            "Set Lifecycle Settings to 'Keep only the last version of the file'.",
        )
    return None
