from __future__ import annotations

import pytest

from keepsake.config import ConfigError, load_profiles, resolve_profile

ENV = {
    "KEEPSAKE_ENDPOINT": "https://s3.us-east-001.backblazeb2.com",
    "KEEPSAKE_JANE_BUCKET": "media-jane",
    "KEEPSAKE_JANE_ID": "id1",
    "KEEPSAKE_JANE_KEY": "key1",
    "KEEPSAKE_JOHN_BUCKET": "media-john",
    "KEEPSAKE_JOHN_ID": "id2",
    "KEEPSAKE_JOHN_KEY": "key2",
}


def test_discovers_a_profile_per_bucket_var():
    profiles = load_profiles(ENV)
    assert sorted(profiles) == ["jane", "john"]
    assert profiles["jane"].bucket == "media-jane"
    assert profiles["jane"].endpoint.endswith("backblazeb2.com")


def test_unprefixed_vars_are_ignored():
    profiles = load_profiles({**ENV, "AWS_BUCKET": "unrelated", "BACKUP_BUCKET": "nope"})
    assert sorted(profiles) == ["jane", "john"]


def test_per_profile_endpoint_overrides_the_shared_one():
    profiles = load_profiles(
        {**ENV, "KEEPSAKE_JOHN_ENDPOINT": "https://s3.eu-central-003.backblazeb2.com"}
    )
    assert "eu-central-003" in profiles["john"].endpoint
    assert "us-east-001" in profiles["jane"].endpoint


def test_incomplete_profile_names_the_missing_vars():
    with pytest.raises(ConfigError, match="KEEPSAKE_JANE_KEY"):
        load_profiles({k: v for k, v in ENV.items() if k != "KEEPSAKE_JANE_KEY"})


def test_underscores_are_allowed_in_profile_names():
    profiles = load_profiles(
        {
            "KEEPSAKE_ENDPOINT": ENV["KEEPSAKE_ENDPOINT"],
            "KEEPSAKE_OLD_STUFF_BUCKET": "b",
            "KEEPSAKE_OLD_STUFF_ID": "i",
            "KEEPSAKE_OLD_STUFF_KEY": "k",
        }
    )
    assert "old_stuff" in profiles


def test_resolve_requires_a_choice_when_several_exist(monkeypatch):
    monkeypatch.delenv("KEEPSAKE_PROFILE", raising=False)
    profiles = load_profiles(ENV)
    with pytest.raises(ConfigError, match="multiple profiles"):
        resolve_profile(None, profiles)
    assert resolve_profile("jane", profiles).bucket == "media-jane"


def test_resolve_defaults_to_the_only_profile(monkeypatch):
    monkeypatch.delenv("KEEPSAKE_PROFILE", raising=False)
    only = {k: v for k, v in ENV.items() if not k.startswith("KEEPSAKE_JOHN")}
    assert resolve_profile(None, load_profiles(only)).name == "jane"


def test_unknown_profile_is_rejected():
    with pytest.raises(ConfigError, match="unknown profile"):
        resolve_profile("nope", load_profiles(ENV))
