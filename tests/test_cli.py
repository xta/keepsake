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
    monkeypatch.setattr(cli, "_open", lambda name: (profile, bucket))
    return bucket


def test_version():
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "keepsake" in result.stdout


def test_ls_renders_a_survey(library):
    result = runner.invoke(cli.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "test-bucket" in result.stdout
    assert ".mov" in result.stdout
    assert "media/" in result.stdout


def test_ls_files_lists_every_key(library):
    result = runner.invoke(cli.app, ["ls", "--files"])
    assert result.exit_code == 0, result.output
    assert "media/2025/IMG_4471.mov" in result.stdout


def test_check_reports_expected_states(library):
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0, result.output
    assert "media-no-sidecar" in result.stdout
    assert "non-media-present" in result.stdout


def test_check_exits_nonzero_on_errors(library):
    library.seed("media/2026/ghost.mp4.json", b"{}")
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "sidecar-no-media" in result.stdout


def test_reindex_prints_valid_json(library):
    result = runner.invoke(cli.app, ["reindex"])
    assert result.exit_code == 0, result.output
    index = json.loads(result.stdout)
    assert index["count"] == 1
    assert index["items"][0]["path"] == "media/2026/piano.mp4"
    assert index["items"][0]["title"] == "Spring Recital"


def test_reindex_output_file_does_not_touch_the_bucket(library, tmp_path):
    out = tmp_path / "out.json"
    result = runner.invoke(cli.app, ["reindex", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["count"] == 1
    assert library.head("index.json") is None


def test_no_profiles_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(cli, "_profiles", lambda: {})
    result = runner.invoke(cli.app, ["ls"])
    assert result.exit_code == 1
