"""keepsake command line.

Four verbs, matching the four things anyone actually wants to do:

    profiles   can I reach my buckets?
    status     what is in this bucket, and is it healthy?
    sync       make the bucket match the convention
    version

`sync` writes only with `--apply`. Without it, it prints exactly what it would
do and touches nothing.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.table import Table
from ulid import ULID

from keepsake import __version__
from keepsake.config import ConfigError, load_dotenv_if_present, load_profiles, resolve_profile
from keepsake.core import adopt as adopt_mod
from keepsake.core import check as check_mod
from keepsake.core import index as index_mod
from keepsake.core.classify import classify
from keepsake.core.survey import human_bytes, survey
from keepsake.storage.base import INDEX_KEY

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Manage keepsake libraries in object storage.",
)
console = Console()
err = Console(stderr=True)

ProfileOpt = Annotated[
    Optional[str], typer.Option("--profile", "-p", help="Profile name from .env")
]
PrefixOpt = Annotated[str, typer.Option("--prefix", help="Restrict to this key prefix")]

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


def _open(profile_name: str | None, *, writable: bool = False):
    profiles = _profiles()
    try:
        profile = resolve_profile(profile_name, profiles)
    except ConfigError as exc:
        _fail(str(exc))
    return profile, profile.open(readonly=not writable)


def _header(profile, extra: str = "") -> None:
    console.print(f"\n[bold]{profile.name}[/] -> [cyan]{profile.bucket}[/]  {extra}\n")


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


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
def status(
    profile: ProfileOpt = None,
    prefix: PrefixOpt = "",
    depth: Annotated[int, typer.Option("--depth", help="Prefix grouping depth")] = 1,
    show_files: Annotated[
        bool, typer.Option("--files", help="List every key instead of summarising")
    ] = False,
    deep: Annotated[
        bool, typer.Option("--deep/--no-deep", help="Fetch and validate every sidecar")
    ] = True,
) -> None:
    """What is in this bucket, and is it healthy?"""
    prof, bucket = _open(profile)
    result = classify(bucket.list(prefix))
    report = survey(result, prefix_depth=depth)

    _header(prof, f"{report.total_objects:,} objects, {human_bytes(report.total_bytes)}")

    if show_files:
        for key in sorted(result.objects):
            console.print(f"  {key}  [dim]{human_bytes(result.size_of(key))}[/]")
        console.print()
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

    findings = check_mod.check(result, bucket, read_sidecars=deep)
    lifecycle = check_mod.lifecycle_finding(bucket)
    if lifecycle is not None:
        findings.append(lifecycle)

    if findings:
        console.print("\n[bold]findings[/]")
        for finding in findings:
            style = LEVEL_STYLE[finding.level]
            location = f" [dim]{finding.key}[/]" if finding.key else ""
            console.print(f"[{style}]{finding.level:>5}[/] {finding.code}{location}")
            console.print(f"        {finding.message}")
    else:
        console.print("\n[green]no findings[/]")
    console.print()

    if any(f.level == "error" for f in findings):
        raise typer.Exit(1)


def _index_is_current(bucket, fresh: dict[str, Any]) -> bool:
    """True if the stored catalog already matches the one we just built.

    `generated_at` is excluded from the comparison: it changes on every build,
    and rewriting an identical catalog just to bump a timestamp would create a
    new object version on every run for no gain.
    """
    try:
        stored = json.loads(bucket.get(INDEX_KEY))
    except (KeyError, json.JSONDecodeError):
        return False
    return stored.get("items") == fresh["items"] and stored.get("count") == fresh["count"]


@app.command()
def sync(
    profile: ProfileOpt = None,
    prefix: PrefixOpt = "",
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually write the changes")
    ] = False,
    details: Annotated[
        bool, typer.Option("--details", "-d", help="Show full sidecar contents in the plan")
    ] = False,
) -> None:
    """Make the bucket match the convention.

    Writes a stub sidecar for any media that lacks one, then rebuilds
    index.json from every sidecar. Idempotent: running it again does nothing.
    """
    prof, bucket = _open(profile, writable=apply)
    result = classify(bucket.list(prefix))
    stubs = adopt_mod.plan(result, new_id=lambda: str(ULID()))

    if apply:
        _header(prof)
        if stubs:
            written = adopt_mod.apply(bucket, stubs)
            console.print(f"wrote [green]{_plural(written, 'sidecar')}[/]")
            # Sidecars are the source of truth, so the catalog is built from
            # the bucket as it stands after they land.
            result = classify(bucket.list(prefix))

        index = index_mod.build_index(result, bucket)
        if _index_is_current(bucket, index):
            console.print("index.json [dim]already current[/]")
        else:
            size = index_mod.write(bucket, index)
            console.print(
                f"wrote [green]index.json[/] ({_plural(index['count'], 'item')}, {human_bytes(size)})"
            )
        console.print()
        return

    index = index_mod.build_index(result, bucket)
    # The plan is built before the stubs exist, so the catalog it reports is
    # the one that would result from writing them.
    planned_count = index["count"] + len(stubs)

    _header(prof)
    if stubs:
        console.print(f"[bold]{_plural(len(stubs), 'sidecar')}[/] to write")
        for stub in stubs:
            console.print(f"  [green]+[/] {stub.sidecar_key}")
            if details:
                for field, value in stub.payload.items():
                    console.print(f"      [dim]{field:<12}[/]{value}")
        if not details:
            console.print("  [dim]--details to see their contents[/]")
    else:
        console.print("[dim]no sidecars needed[/]")

    if not result.index_present:
        console.print(f"\nindex.json to create ({_plural(planned_count, 'item')})")
    elif stubs or not _index_is_current(bucket, index):
        console.print(f"\nindex.json to rebuild ({_plural(planned_count, 'item')})")
    else:
        console.print("\nindex.json [dim]already current[/]")

    if stubs or not result.index_present:
        console.print("\n[yellow]nothing written.[/] re-run with --apply\n")
    else:
        console.print("\n[green]already in sync[/]\n")


@app.command()
def edit(
    profile: ProfileOpt = None,
    prefix: PrefixOpt = "",
) -> None:
    """Browse the library and fill in titles, dates, tags, and notes."""
    from keepsake.tui import KeepsakeApp

    prof, bucket = _open(profile, writable=True)
    KeepsakeApp(bucket, label=prof.bucket, prefix=prefix).run()


if __name__ == "__main__":
    app()
