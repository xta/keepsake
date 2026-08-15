"""keepsake command line.

Phase 1 is read-only: every bucket is opened with `readonly=True`, so the
storage layer refuses writes regardless of what a command asks for.
"""

from __future__ import annotations

import sys
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from keepsake import __version__
from keepsake.config import ConfigError, load_dotenv_if_present, load_profiles, resolve_profile
from keepsake.core import check as check_mod
from keepsake.core.classify import classify
from keepsake.core.index import build_index, serialize
from keepsake.core.survey import human_bytes, survey

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Manage keepsake libraries in object storage. Phase 1: read-only.",
)
console = Console()
err = Console(stderr=True)

ProfileOpt = Annotated[
    Optional[str], typer.Option("--profile", "-p", help="Profile name from .env")
]

LEVEL_STYLE = {"error": "bold red", "warn": "yellow", "info": "dim"}


def _fail(message: str) -> None:
    err.print(f"[bold red]error[/] {message}")
    raise typer.Exit(1)


def _profiles():
    load_dotenv_if_present()
    try:
        return load_profiles()
    except ConfigError as exc:
        _fail(str(exc))


def _open(profile_name: str | None):
    profiles = _profiles()
    try:
        profile = resolve_profile(profile_name, profiles)
    except ConfigError as exc:
        _fail(str(exc))
    return profile, profile.open(readonly=True)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"keepsake {__version__}")


@app.command("profiles")
def profiles_cmd(
    verify: Annotated[
        bool, typer.Option("--verify", help="Reach each bucket with HeadBucket")
    ] = False,
) -> None:
    """List profiles discovered in the environment."""
    profiles = _profiles()
    table = Table("profile", "bucket", "endpoint", box=None, pad_edge=False)
    if verify:
        table.add_column("status")
    for name in sorted(profiles):
        profile = profiles[name]
        row = [name, profile.bucket, profile.endpoint]
        if verify:
            try:
                profile.open(readonly=True).verify()
                row.append("[green]ok[/]")
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim
                row.append(f"[red]{type(exc).__name__}[/]: {exc}")
        table.add_row(*row)
    console.print(table)


@app.command()
def ls(
    profile: ProfileOpt = None,
    prefix: Annotated[str, typer.Option("--prefix", help="Only list under this prefix")] = "",
    depth: Annotated[int, typer.Option("--depth", help="Prefix grouping depth")] = 1,
    show_files: Annotated[
        bool, typer.Option("--files", help="List every key instead of summarising")
    ] = False,
) -> None:
    """Survey a bucket: what is in it, and what adopting it would involve."""
    prof, bucket = _open(profile)
    result = classify(bucket.list(prefix))
    report = survey(result, prefix_depth=depth)

    console.print(
        f"\n[bold]{prof.name}[/] -> [cyan]{prof.bucket}[/]  "
        f"{report.total_objects:,} objects, {human_bytes(report.total_bytes)}\n"
    )

    if show_files:
        for key in sorted(result.objects):
            console.print(f"  {key}  [dim]{human_bytes(result.size_of(key))}[/]")
        return

    ext_table = Table("extension", "count", "size", box=None, pad_edge=False)
    for ext, stats in list(report.by_extension.items())[:15]:
        ext_table.add_row(ext, f"{stats.count:,}", human_bytes(stats.bytes))
    console.print(ext_table)

    console.print("\n[bold]by prefix[/]")
    prefix_table = Table("prefix", "count", "size", box=None, pad_edge=False)
    for name, stats in list(report.by_prefix.items())[:15]:
        prefix_table.add_row(name, f"{stats.count:,}", human_bytes(stats.bytes))
    console.print(prefix_table)

    console.print(
        f"\nindexed: [green]{report.sidecars_present:,}[/]   "
        f"needs a sidecar: [yellow]{report.sidecars_needed:,}[/]   "
        f"index.json: {'present' if report.index_present else '[yellow]absent[/]'}"
    )
    if report.non_media:
        console.print(
            f"[yellow]{len(report.non_media):,}[/] object(s) do not look like media "
            f"({human_bytes(report.non_media_bytes)}). Run with --files to see them."
        )
    console.print()


@app.command()
def check(
    profile: ProfileOpt = None,
    prefix: Annotated[str, typer.Option("--prefix")] = "",
    deep: Annotated[
        bool, typer.Option("--deep/--no-deep", help="Fetch and validate every sidecar")
    ] = True,
) -> None:
    """Report the failure modes from SPEC.md against a bucket."""
    prof, bucket = _open(profile)
    result = classify(bucket.list(prefix))
    findings = check_mod.check(result, bucket, read_sidecars=deep)

    lifecycle = check_mod.lifecycle_finding(bucket)
    if lifecycle is not None:
        findings.append(lifecycle)

    console.print(f"\n[bold]{prof.name}[/] -> [cyan]{prof.bucket}[/]\n")
    if not findings:
        console.print("[green]no findings[/]\n")
        return

    for finding in findings:
        style = LEVEL_STYLE[finding.level]
        location = f" [dim]{finding.key}[/]" if finding.key else ""
        console.print(f"[{style}]{finding.level:>5}[/] {finding.code}{location}")
        console.print(f"        {finding.message}")

    errors = sum(1 for f in findings if f.level == "error")
    console.print()
    if errors:
        raise typer.Exit(1)


@app.command()
def reindex(
    profile: ProfileOpt = None,
    prefix: Annotated[str, typer.Option("--prefix")] = "",
    output: Annotated[
        Optional[str], typer.Option("--output", "-o", help="Write the index here instead of stdout")
    ] = None,
) -> None:
    """Build index.json and print it. Phase 1 never writes to the bucket."""
    _prof, bucket = _open(profile)
    result = classify(bucket.list(prefix))
    index = build_index(result, bucket)
    payload = serialize(index)

    if output:
        with open(output, "wb") as handle:
            handle.write(payload)
        console.print(
            f"wrote {index['count']:,} item(s) to [cyan]{output}[/] "
            "[dim](local file; the bucket was not modified)[/]"
        )
    else:
        sys.stdout.write(payload.decode("utf-8") + "\n")


if __name__ == "__main__":
    app()
