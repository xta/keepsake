"""One-off: reissue every sidecar `id` as a UUIDv7.

SPEC.md says `id` never changes, and that rule is not being softened -- this is
a deliberate, one-time reissue across an archive small enough to count on two
hands, before anything outside the bucket references an id. After this, the rule
holds again.

Nothing else in the sidecar is touched. The file is re-read, one key is
replaced, and the rest is written back exactly as found, so titles, dates, tags,
locations, notes, and any unknown fields survive untouched.

    uv run python migrate_ids.py            # dry run, writes nothing
    uv run python migrate_ids.py --apply
"""

from __future__ import annotations

import json
import sys

from keepsake.config import load_dotenv_if_present, load_profiles
from keepsake.core.classify import classify
from keepsake.models import new_id

HUMAN = ("title", "recorded_at", "tags", "location", "notes")


def main(apply: bool) -> int:
    load_dotenv_if_present()
    profiles = load_profiles()
    total = failed = 0

    for name in sorted(profiles):
        profile = profiles[name]
        bucket = profile.open(readonly=not apply)
        result = classify(bucket.list())
        print(f"\n{name} -> {profile.bucket}")

        for media_key, sidecar_key in sorted(result.media.items()):
            try:
                payload = json.loads(bucket.get(sidecar_key))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sidecar_key}: unreadable ({exc})")
                failed += 1
                continue
            if not isinstance(payload, dict):
                print(f"  ! {sidecar_key}: not a JSON object")
                failed += 1
                continue

            old = payload.get("id", "(none)")
            fresh = new_id()
            kept = [f for f in HUMAN if payload.get(f)]

            print(f"  {media_key}")
            print(f"      id  {old}  ->  {fresh}")
            if kept:
                print(f"      keeping: {', '.join(kept)}")

            if apply:
                payload["id"] = fresh
                try:
                    bucket.put(
                        sidecar_key,
                        json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
                        content_type="application/json",
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"      ! write failed: {exc}")
                    failed += 1
                    continue
            total += 1

    if apply:
        print(f"\nrewrote {total} sidecar(s).")
        print("index.json inlines sidecars, so rebuild it:  uv run keepsake sync --apply")
    else:
        print(f"\n{total} sidecar(s) would be rewritten. Nothing written.")
        print("Re-run with --apply to do it.")
    if failed:
        print(f"{failed} problem(s) above.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
