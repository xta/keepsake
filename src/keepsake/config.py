"""Profile discovery.

Profiles come from the environment, so `.env` *is* the profile registry --
adding a bucket is three lines and no code:

    KEEPSAKE_ENDPOINT=https://s3.us-east-001.backblazeb2.com

    KEEPSAKE_FAMILY_BUCKET=media-main
    KEEPSAKE_FAMILY_ID=...
    KEEPSAKE_FAMILY_KEY=...

A profile is discovered from each `KEEPSAKE_<NAME>_BUCKET`. Endpoint falls back
to the shared `KEEPSAKE_ENDPOINT` when a profile does not override it.

The `KEEPSAKE_` prefix is load-bearing: discovery scans the whole process
environment, not just `.env`, so an unprefixed `<NAME>_BUCKET` would collide
with unrelated variables already in the shell.

`load_profiles` is the single resolution point, so another credential source
can slot in behind it without any caller changing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

BUCKET_VAR = re.compile(r"^KEEPSAKE_([A-Z0-9_]+)_BUCKET$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    bucket: str
    endpoint: str
    key_id: str
    app_key: str

    def open(self, *, readonly: bool = True):
        from keepsake.storage.b2 import B2Bucket

        return B2Bucket(
            self.bucket,
            self.endpoint,
            self.key_id,
            self.app_key,
            readonly=readonly,
        )


def load_dotenv_if_present(start: Path | None = None) -> Path | None:
    """Load a `.env` from the cwd or the nearest parent that has one."""
    from dotenv import load_dotenv

    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return candidate
    return None


def load_profiles(env: dict[str, str] | None = None) -> dict[str, Profile]:
    env = dict(os.environ if env is None else env)
    shared_endpoint = env.get("KEEPSAKE_ENDPOINT", "").strip()

    profiles: dict[str, Profile] = {}
    for var, bucket in env.items():
        match = BUCKET_VAR.match(var)
        if not match or not bucket.strip():
            continue
        upper = match.group(1)
        name = upper.lower()

        endpoint = env.get(f"KEEPSAKE_{upper}_ENDPOINT", "").strip() or shared_endpoint
        key_id = env.get(f"KEEPSAKE_{upper}_ID", "").strip()
        app_key = env.get(f"KEEPSAKE_{upper}_KEY", "").strip()

        missing = [
            var
            for var, value in (
                ("KEEPSAKE_ENDPOINT", endpoint),
                (f"KEEPSAKE_{upper}_ID", key_id),
                (f"KEEPSAKE_{upper}_KEY", app_key),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"profile {name!r} is incomplete: set {', '.join(missing)}."
            )

        profiles[name] = Profile(
            name=name,
            bucket=bucket.strip(),
            endpoint=endpoint,
            key_id=key_id,
            app_key=app_key,
        )
    return profiles


def resolve_profile(name: str | None, profiles: dict[str, Profile]) -> Profile:
    """Flag, then KEEPSAKE_PROFILE, then the sole profile if there is only one."""
    if not profiles:
        raise ConfigError(
            "no profiles found. Create a .env with KEEPSAKE_ENDPOINT and at least "
            "one KEEPSAKE_<NAME>_BUCKET / _ID / _KEY triple. See .env.example."
        )
    chosen = name or os.environ.get("KEEPSAKE_PROFILE") or ""
    chosen = chosen.strip().lower()
    if not chosen:
        if len(profiles) == 1:
            return next(iter(profiles.values()))
        raise ConfigError(
            f"multiple profiles ({', '.join(sorted(profiles))}); "
            "pick one with --profile or set KEEPSAKE_PROFILE."
        )
    if chosen not in profiles:
        raise ConfigError(
            f"unknown profile {chosen!r}. Known: {', '.join(sorted(profiles))}."
        )
    return profiles[chosen]
