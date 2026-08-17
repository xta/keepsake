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
from keepsake.core.thumbs import ffmpeg_available
from keepsake.storage.local import LocalDirBucket

runner = CliRunner()

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg and ffprobe are not on PATH"
)


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
    monkeypatch.setattr(cli, "_open", lambda name, writable=False: [(profile, bucket)])
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
        # notes.txt is not recognised media, so it is not adopted by default.
        assert "1 sidecar to write" in result.stdout
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
        # piano.mp4 already had a sidecar; IMG_4471.mov gets a stub. notes.txt
        # is not recognised media and stays out of the library.
        assert catalog["count"] == 2
        assert [item["path"] for item in catalog["items"]] == [
            "media/2025/IMG_4471.mov",
            "media/2026/piano.mp4",
        ]
        assert library.head("notes.txt.json") is None

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
        assert json.loads(library.get("index.json"))["count"] == 3

    def test_status_after_sync_reports_only_the_stray(self, library):
        """Every media file is adopted; notes.txt is deliberately left out."""
        runner.invoke(cli.app, ["sync", "--apply"])
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        assert "non-media-present" in result.stdout


class TestSyncThumbs:
    """The gated pass. `library`'s fixture media is not decodable video, so
    these cover the plan and the gate rather than the rendering -- that runs
    against real ffmpeg in test_thumbs.py."""

    def test_no_thumbnail_work_is_mentioned_without_the_flag(self, library):
        result = runner.invoke(cli.app, ["sync"])
        assert "thumbnail" not in result.stdout.lower()

    @needs_ffmpeg
    def test_the_plan_lists_what_would_be_rendered(self, library):
        result = runner.invoke(cli.app, ["sync", "--thumbs"])

        assert result.exit_code == 0, result.output
        # piano.mp4 already has a thumbnail in the fixture; IMG_4471.mov does not.
        assert "1 thumbnail to render" in result.stdout
        assert "media/2025/IMG_4471.mov.jpg" in result.stdout
        assert "media/2026/piano.mp4.jpg" not in result.stdout
        assert "nothing written" in result.stdout
        assert library.head("media/2025/IMG_4471.mov.jpg") is None

    def test_a_missing_ffmpeg_is_a_note_rather_than_a_failure(
        self, library, monkeypatch
    ):
        """Degrade and say so. The rest of sync is useful without ffmpeg, and
        stopping the run would make `--thumbs` a trap on a machine that has
        never installed it."""
        monkeypatch.setattr(cli.thumbs_mod, "ffmpeg_available", lambda: False)

        result = runner.invoke(cli.app, ["sync", "--thumbs", "--apply"])

        assert result.exit_code == 0, result.output
        assert "brew install ffmpeg" in result.output
        # The ordinary passes still ran.
        assert library.head("media/2025/IMG_4471.mov.json") is not None
        assert library.head("index.json") is not None

    @needs_ffmpeg
    def test_a_video_that_cannot_be_decoded_is_reported_and_skipped(self, library):
        """The fixture's `IMG_4471.mov` is four kilobytes of 'y'. ffmpeg will
        refuse it, which is the realistic failure for a corrupt file in a real
        library."""
        result = runner.invoke(cli.app, ["sync", "--thumbs", "--apply"])

        assert result.exit_code == 0, result.output
        assert "rendered 0 thumbnails" in result.stdout
        assert "media/2025/IMG_4471.mov" in result.output
        assert library.head("media/2025/IMG_4471.mov.jpg") is None
        # ...and the catalog was still rebuilt.
        assert json.loads(library.get("index.json"))["count"] == 2
        assert library.head("media/2025/IMG_4471.mov.json") is not None
        assert library.head("notes.txt.json") is None

    def test_adopt_all_takes_the_stray_too(self, library):
        runner.invoke(cli.app, ["sync", "--apply", "--adopt-all"])
        assert library.head("notes.txt.json") is not None
        assert json.loads(library.get("index.json"))["count"] == 3


class TestAdd:
    @pytest.fixture
    def clip(self, tmp_path):
        """A local file to upload, with a real QuickTime header."""
        from datetime import datetime, timezone

        from test_moov import movie, mvhd_v0, seconds_since_1904

        stamp = seconds_since_1904(datetime(2026, 5, 22, tzinfo=timezone.utc))
        source = tmp_path / "incoming"
        source.mkdir()
        path = source / "recital.mov"
        path.write_bytes(movie(mvhd_v0(creation=stamp, duration=600)).getvalue())
        return path

    def test_dry_run_writes_nothing(self, library, clip):
        result = runner.invoke(cli.app, ["add", str(clip), "--dry-run"])
        assert "2026/05/recital.mov" in result.stdout
        assert "nothing written" in result.stdout
        assert library.head("2026/05/recital.mov") is None

    def test_dry_run_says_plainly_that_it_is_clear(self, library, clip):
        """"No red" is not a verdict; say so in words."""
        result = runner.invoke(cli.app, ["add", str(clip), "--dry-run"])
        assert "no problems found" in result.stdout
        assert result.exit_code == 0

    def test_dry_run_counts_the_refusals(self, library, clip):
        stray = clip.parent / "no-extension"
        stray.write_bytes(b"x" * 64)
        result = runner.invoke(cli.app, ["add", str(clip), str(stray), "--dry-run"])
        assert "1 file ready" in result.stdout
        assert "1 refused" in result.stdout
        assert "no problems found" not in result.stdout
        assert result.exit_code == 1

    def test_a_date_read_from_the_file_is_reported(self, library, clip):
        result = runner.invoke(cli.app, ["add", str(clip), "--dry-run"])
        assert "recorded 2026-05-22" in result.stdout

    def test_a_missing_date_says_it_fell_back_to_today(self, library, tmp_path):
        """Otherwise a video shot this month and one with no date look alike."""
        from test_moov import movie, mvhd_v0

        undated = tmp_path / "incoming" / "undated.mov"
        undated.parent.mkdir(exist_ok=True)
        undated.write_bytes(movie(mvhd_v0(creation=0, duration=600)).getvalue())

        result = runner.invoke(cli.app, ["add", str(undated), "--dry-run"])
        assert "no date in file, filed under today" in result.stdout

    def test_uploads_media_sidecar_and_index(self, library, clip):
        result = runner.invoke(cli.app, ["add", str(clip), "--yes", "--no-edit"])
        assert result.exit_code == 0, result.output

        assert library.get("2026/05/recital.mov") == clip.read_bytes()
        sidecar = json.loads(library.get("2026/05/recital.mov.json"))
        assert sidecar["recorded_at"] == "2026-05-22"
        assert sidecar["duration_s"] == 1.0
        assert "2026/05/recital.mov" in {
            item["path"] for item in json.loads(library.get("index.json"))["items"]
        }

    def test_title_is_written_when_given(self, library, clip):
        runner.invoke(
            cli.app, ["add", str(clip), "-t", "Spring Recital", "--yes", "--no-edit"]
        )
        sidecar = json.loads(library.get("2026/05/recital.mov.json"))
        assert sidecar["title"] == "Spring Recital"

    def test_into_overrides_the_dated_layout(self, library, clip):
        runner.invoke(
            cli.app, ["add", str(clip), "--into", "home-movies", "--yes", "--no-edit"]
        )
        assert library.head("home-movies/recital.mov") is not None

    def test_into_slash_warns_and_uses_the_root(self, library, clip):
        result = runner.invoke(
            cli.app, ["add", str(clip), "--into", "/", "--yes", "--no-edit"]
        )
        assert "bucket root" in result.stdout
        assert library.head("recital.mov") is not None

    def test_refuses_to_overwrite(self, library, clip):
        runner.invoke(cli.app, ["add", str(clip), "--yes", "--no-edit"])
        result = runner.invoke(cli.app, ["add", str(clip), "--yes", "--no-edit"])
        assert result.exit_code == 1
        assert "already exists" in result.stdout

    def test_declining_the_confirmation_writes_nothing(self, library, clip):
        result = runner.invoke(cli.app, ["add", str(clip), "--no-edit"], input="n\n")
        assert result.exit_code == 1
        assert library.head("2026/05/recital.mov") is None

    def test_title_with_several_files_is_an_error(self, library, clip):
        other = clip.parent / "second.mov"
        other.write_bytes(clip.read_bytes())
        result = runner.invoke(
            cli.app, ["add", str(clip), str(other), "-t", "One Title", "--yes"]
        )
        assert result.exit_code == 1
        assert "single file" in result.output

    def test_a_refused_file_does_not_stop_the_others(self, library, clip):
        stray = clip.parent / "no-extension"
        stray.write_bytes(b"x" * 64)

        result = runner.invoke(
            cli.app, ["add", str(clip), str(stray), "--yes", "--no-edit"]
        )

        assert library.head("2026/05/recital.mov") is not None
        assert library.head("no-extension") is None
        # Non-zero because something was refused, even though the rest landed.
        assert result.exit_code == 1

    def test_requires_a_profile_when_several_exist(self, clip, monkeypatch):
        from keepsake.config import Profile

        def two(name, writable=False):
            return [
                (Profile(n, n, "https://s3.example", "k", "s"), None)
                for n in ("rex", "sam")
            ]

        monkeypatch.setattr(cli, "_open", two)
        result = runner.invoke(cli.app, ["add", str(clip), "--yes"])
        assert result.exit_code == 1
        assert "which library" in result.output


class TestSet:
    """Metadata from the shell, so a CLI-only workflow is complete."""

    def test_sets_a_title(self, library):
        result = runner.invoke(
            cli.app, ["set", "piano.mp4", "-p", "test", "--title", "Spring Recital"]
        )
        assert result.exit_code == 0, result.output
        stored = json.loads(library.get("media/2026/piano.mp4.json"))
        assert stored["title"] == "Spring Recital"

    def test_resolves_a_bare_filename_to_its_key(self, library):
        result = runner.invoke(cli.app, ["set", "piano.mp4", "-p", "test", "-t", "x"])
        assert "media/2026/piano.mp4" in result.stdout

    def test_accepts_the_full_key_too(self, library):
        result = runner.invoke(
            cli.app, ["set", "media/2026/piano.mp4", "-p", "test", "-t", "x"]
        )
        assert result.exit_code == 0, result.output

    def test_tags_split_on_commas(self, library):
        runner.invoke(
            cli.app, ["set", "piano.mp4", "-p", "test", "--tags", "piano, school"]
        )
        stored = json.loads(library.get("media/2026/piano.mp4.json"))
        assert stored["tags"] == ["piano", "school"]

    def test_one_field_can_span_several_files(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        result = runner.invoke(
            cli.app,
            ["set", "piano.mp4", "IMG_4471.mov", "-p", "test", "--tags", "transfer"],
        )
        assert result.exit_code == 0, result.output
        for key in ("media/2026/piano.mp4.json", "media/2025/IMG_4471.mov.json"):
            assert json.loads(library.get(key))["tags"] == ["transfer"]

    def test_an_empty_value_clears_the_field(self, library):
        runner.invoke(cli.app, ["set", "piano.mp4", "-p", "test", "--title", ""])
        assert "title" not in json.loads(library.get("media/2026/piano.mp4.json"))

    def test_dry_run_writes_nothing(self, library):
        result = runner.invoke(
            cli.app, ["set", "piano.mp4", "-p", "test", "-t", "New", "--dry-run"]
        )
        assert "nothing written" in result.stdout
        assert json.loads(library.get("media/2026/piano.mp4.json"))["title"] == "Spring Recital"

    def test_setting_the_same_value_writes_nothing(self, library):
        result = runner.invoke(
            cli.app, ["set", "piano.mp4", "-p", "test", "-t", "Spring Recital"]
        )
        assert "already set" in result.stdout

    def test_rebuilds_the_index(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        runner.invoke(cli.app, ["set", "piano.mp4", "-p", "test", "-t", "Renamed"])
        catalog = json.loads(library.get("index.json"))
        entry = next(i for i in catalog["items"] if i["path"].endswith("piano.mp4"))
        assert entry["title"] == "Renamed"

    def test_an_off_spec_date_is_refused(self, library):
        """SPEC requires YYYY-MM-DD; the archive must read the same forever."""
        result = runner.invoke(
            cli.app, ["set", "piano.mp4", "-p", "test", "--recorded-at", "05/22/26"]
        )
        assert result.exit_code == 1
        assert "not a SPEC date" in result.output
        assert "recorded_at" not in json.loads(library.get("media/2026/piano.mp4.json"))

    def test_an_unknown_file_is_a_clean_error(self, library):
        result = runner.invoke(cli.app, ["set", "nope.mov", "-p", "test", "-t", "x"])
        assert result.exit_code == 1
        assert "no file matching" in result.output

    def test_no_fields_is_a_clean_error(self, library):
        result = runner.invoke(cli.app, ["set", "piano.mp4", "-p", "test"])
        assert result.exit_code == 1
        assert "nothing to set" in result.output

    def test_title_across_several_files_is_refused(self, library):
        runner.invoke(cli.app, ["sync", "--apply"])
        result = runner.invoke(
            cli.app, ["set", "piano.mp4", "IMG_4471.mov", "-p", "test", "-t", "One"]
        )
        assert result.exit_code == 1
        assert "single file" in result.output


def test_no_profiles_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(cli, "_profiles", lambda: {})
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
