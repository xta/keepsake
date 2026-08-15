"""CLI smoke tests.

These exercise the rendering paths by swapping the B2 backend for a local
directory, so the whole suite still runs with no network and no credentials.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from keepsake import cli
from keepsake.config import Profile
from keepsake.storage.local import LocalDirBucket

runner = CliRunner()


@pytest.fixture
def library(tmp_path, monkeypatch):
    bucket = LocalDirBucket(tmp_path, name="test-bucket", readonly=False)
    bucket.seed("media/2026/piano.mp4", b"x" * 2048)
    bucket.seed(
        "media/2026/piano.mp4.json",
        json.dumps(
            {
                "schema": 1,
                "id": "01HQ8XKPZR4M2N7QVWJT3YFBCD",
                "file": "piano.mp4",
                "uploaded_at": "2026-04-14T02:11:09Z",
                "title": "Spring Recital",
            }
        ).encode(),
    )
    bucket.seed("media/2026/piano.mp4.jpg", b"thumb")
    bucket.seed("media/2025/IMG_4471.mov", b"y" * 4096)
    bucket.seed("notes.txt", b"stray")

    profile = Profile(
        name="test",
        bucket="test-bucket",
        endpoint="https://s3.us-east-001.backblazeb2.com",
        key_id="k",
        app_key="s",
    )
    monkeypatch.setattr(cli, "_open", lambda name, writable=False: (profile, bucket))
    return bucket


def test_version():
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "keepsake" in result.stdout


class TestStatus:
    def test_shows_survey_and_findings_together(self, library):
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0, result.output
        assert "test-bucket" in result.stdout
        assert ".mov" in result.stdout
        assert "findings" in result.stdout
        assert "media-no-sidecar" in result.stdout
        assert "non-media-present" in result.stdout

    def test_files_lists_every_key(self, library):
        result = runner.invoke(cli.app, ["status", "--files"])
        assert result.exit_code == 0, result.output
        assert "media/2025/IMG_4471.mov" in result.stdout

    def test_exits_nonzero_on_errors(self, library):
        library.seed("media/2026/ghost.mp4.json", b"{}")
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 1
        assert "sidecar-no-media" in result.stdout


class TestSync:
    def test_plan_writes_nothing(self, library):
        result = runner.invoke(cli.app, ["sync"])
        assert result.exit_code == 0, result.output
        assert "2 sidecars to write" in result.stdout
        assert "IMG_4471.mov.json" in result.stdout
        assert "index.json to create" in result.stdout
        assert "nothing written" in result.stdout
        assert library.head("media/2025/IMG_4471.mov.json") is None
        assert library.head("index.json") is None

    def test_details_shows_sidecar_contents(self, library):
        result = runner.invoke(cli.app, ["sync", "--details"])
        assert "uploaded_at" in result.stdout
        assert "video/quicktime" in result.stdout

    def test_apply_writes_sidecars_and_the_catalog(self, library):
        result = runner.invoke(cli.app, ["sync", "--apply"])
        assert result.exit_code == 0, result.output

        assert library.head("media/2025/IMG_4471.mov.json") is not None
        catalog = json.loads(library.get("index.json"))
        # piano.mp4 already had a sidecar; the other two get stubs.
        assert catalog["count"] == 3
        assert [item["path"] for item in catalog["items"]] == [
            "media/2025/IMG_4471.mov",
            "media/2026/piano.mp4",
            "notes.txt",
        ]

    def test_is_idempotent(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        result = runner.invoke(cli.app, ["sync"])
        assert "no sidecars needed" in result.stdout
        assert "already in sync" in result.stdout

    def test_apply_twice_does_not_rewrite_an_unchanged_catalog(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        first = library.head("index.json")
        result = runner.invoke(cli.app, ["sync", "--apply"])
        assert "already current" in result.stdout
        assert library.head("index.json").size == first.size

    def test_new_media_is_picked_up_on_the_next_sync(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        library.seed("media/2026/new-clip.mp4", b"z" * 512)

        result = runner.invoke(cli.app, ["sync", "--apply"])

        assert result.exit_code == 0, result.output
        assert library.head("media/2026/new-clip.mp4.json") is not None
        assert json.loads(library.get("index.json"))["count"] == 4

    def test_status_is_clean_after_sync(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        assert "media-no-sidecar" not in result.stdout


def test_no_profiles_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(cli, "_profiles", lambda: {})
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
