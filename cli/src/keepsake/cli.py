"""keepsake command line.

A verb for each thing anyone actually wants to do:

    profiles   can I reach my buckets?
    status     what is in my libraries, and are they healthy?
    sync       make them match the convention
    add        put new files in
    set        fill in titles, dates, tags and notes from the shell
    edit       ...or the same, in a terminal UI
    version

Either front end completes a job on its own: `add` + `set` never leaves the
shell, and `edit` uploads with `a` and titles in place. `add` ends by opening
the editor only because a title is easiest to type while you still remember
what the file was, and `--no-edit` turns that off.

Omitting `--profile` acts on every library in `.env`; naming one narrows it.
`add` and `set` are the exceptions: they write to one library, so they insist.

`sync` writes only with `--apply`. Without it, it prints exactly what it would
do and touches nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.padding import Padding
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn
from rich.table import Table
from rich.text import Text

from keepsake import __version__
from keepsake.config import (
    ConfigError,
    load_dotenv_if_present,
    load_profiles,
    resolve_profiles,
)
from keepsake.core import adopt as adopt_mod
from keepsake.core import check as check_mod
from keepsake.core import index as index_mod
from keepsake.core import upload as upload_mod
from keepsake.core.classify import classify
from keepsake.core.survey import human_bytes, human_duration, survey
from keepsake.models import new_id
from keepsake.storage.base import INDEX_KEY

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Manage keepsake libraries in object storage.",
)
console = Console()
err = Console(stderr=True)

ProfileOpt = Annotated[
    Optional[str],
    typer.Option("--profile", "-p", help="Profile from .env. Omit to act on all of them."),
]
PrefixOpt = Annotated[str, typer.Option("--prefix", help="Restrict to this key prefix")]

#: `add` writes, so it means one library. Required unless .env holds only one.
TargetProfileOpt = Annotated[
    Optional[str],
    typer.Option("--profile", "-p", help="Profile from .env. Required if you have several."),
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


def _open(profile_name: str | None, *, writable: bool = False):
    """Every selected profile, paired with an open bucket."""
    profiles = _profiles()
    try:
        chosen = resolve_profiles(profile_name, profiles)
    except ConfigError as exc:
        _fail(str(exc))
    return [(p, p.open(readonly=not writable)) for p in chosen]


def _open_one(profile_name: str | None, *, writable: bool = False):
    """Exactly one profile and its bucket.

    Every other verb treats "no --profile" as "all of them", which is right for
    reading and for repair. It is wrong for `add`: a bare `keepsake add` would
    put the same video into every family member's bucket. So the flag is
    required whenever there is more than one library to mean.
    """
    opened = _open(profile_name, writable=writable)
    if len(opened) > 1:
        names = ", ".join(profile.name for profile, _ in opened)
        _fail(
            f"which library? `add` writes to exactly one, and this .env has {names}. "
            "Name it with --profile."
        )
    return opened[0]


def _header(profile, extra: str = "") -> None:
    console.print(f"\n[bold]{profile.name}[/] -> [cyan]{profile.bucket}[/]  {extra}\n")


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def _date_note(candidate, into: str | None) -> str:
    """Where this file's date came from.

    Without this the two cases are indistinguishable: a video actually shot
    this month and a video whose header held no date both land in the current
    `YYYY/MM/`. One is a fact read from the file, the other is a fallback, and
    only the second is worth a second look.
    """
    if candidate.recorded_at:
        return f"[dim]recorded {candidate.recorded_at}[/]"
    if into is not None:
        return "[dim]no date in file[/]"
    return "[yellow]no date in file, filed under today[/]"


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
    """What is in these buckets, and are they healthy?"""
    failed = False
    for prof, bucket in _open(profile):
        failed |= _status_one(prof, bucket, prefix, depth, show_files, deep)
    if failed:
        raise typer.Exit(1)


def _status_one(prof, bucket, prefix, depth, show_files, deep) -> bool:
    """Report one library. True when it has error-level findings."""
    result = classify(bucket.list(prefix))
    report = survey(result, prefix_depth=depth)

    _header(prof, f"{report.total_objects:,} objects, {human_bytes(report.total_bytes)}")

    if show_files:
        for key in sorted(result.objects):
            console.print(f"  {key}  [dim]{human_bytes(result.size_of(key))}[/]")
        console.print()
        return False

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
    return any(f.level == "error" for f in findings)


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
    adopt_all: Annotated[
        bool,
        typer.Option(
            "--adopt-all",
            help="Also adopt files whose extension is not recognised media",
        ),
    ] = False,
) -> None:
    """Make the selected libraries match the convention.

    Writes a stub sidecar for any media that lacks one, then rebuilds
    index.json from every sidecar. Idempotent: running it again does nothing.
    """
    for prof, bucket in _open(profile, writable=apply):
        _sync_one(prof, bucket, prefix, apply, details, adopt_all)


def _sync_one(prof, bucket, prefix, apply, details, adopt_all=False) -> None:
    result = classify(bucket.list(prefix))
    stubs = adopt_mod.plan(
        result, new_id=new_id, include_unrecognised=adopt_all
    )

    if apply:
        _header(prof)
        if stubs:
            written, failures = adopt_mod.apply(bucket, stubs)
            console.print(f"wrote [green]{_plural(written, 'sidecar')}[/]")
            for key, reason in failures:
                err.print(f"[yellow]skipped[/] {key}: {reason}")
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
def add(
    files: Annotated[list[Path], typer.Argument(help="Video or image files to upload")],
    profile: TargetProfileOpt = None,
    title: Annotated[
        Optional[str], typer.Option("--title", "-t", help="Title for a single file")
    ] = None,
    as_name: Annotated[
        Optional[str], typer.Option("--as", help="Store a single file under this name")
    ] = None,
    into: Annotated[
        Optional[str],
        typer.Option(
            "--into",
            help="Destination prefix. Omit for YYYY/MM/ from the recording date; "
            "`/` for the bucket root.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the plan and write nothing")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation")
    ] = False,
    edit_after: Annotated[
        bool,
        typer.Option("--edit/--no-edit", help="Open the editor on what was uploaded"),
    ] = True,
) -> None:
    """Upload files into a library, with a sidecar for each.

    Files land in `YYYY/MM/` taken from the video's own recording date, which
    is the layout these buckets already use. Nothing is ever overwritten.
    """
    prof, bucket = _open_one(profile, writable=not dry_run)

    if len(files) > 1 and (title or as_name):
        _fail("--title and --as describe a single file; drop them for a batch.")

    try:
        candidates = upload_mod.plan_uploads(files, bucket, into=into, as_name=as_name)
    except upload_mod.PrefixError as exc:
        _fail(str(exc))

    _header(prof)
    if into is not None and upload_mod.normalize_prefix(into) == "":
        console.print(
            "[yellow]these files will sit at the bucket root[/], alongside index.json, "
            "rather than in a dated folder.\n"
        )

    # Align the key column so a batch reads down the page rather than ragged.
    width = max((len(c.key) for c in candidates if c.ok), default=0)
    for candidate in candidates:
        if not candidate.ok:
            console.print(f"  [bold red]![/] {candidate.name}")
            # Padding rather than a literal indent, so a wrapped line stays
            # under the message instead of resetting to the left margin.
            console.print(Padding(Text(candidate.problem or "", style="red"), (0, 0, 0, 6)))
            continue

        facts = human_bytes(candidate.size)
        runtime = human_duration(candidate.duration_s)
        if runtime:
            facts += f"  {runtime:>6}"
        console.print(
            f"  [green]+[/] {candidate.key:<{width}}  [dim]{facts:>16}[/]"
            f"  {_date_note(candidate, into)}"
        )

    viable = [c for c in candidates if c.ok]
    refused = [c for c in candidates if not c.ok]
    total = human_bytes(sum(c.size for c in viable))

    # Say plainly whether this is safe to run, rather than leaving it to be
    # inferred from the absence of red.
    if not viable:
        console.print(
            f"\n[bold red]{_plural(len(refused), 'file')} refused. nothing to upload.[/]\n"
        )
        raise typer.Exit(1)
    if refused:
        console.print(
            f"\n{_plural(len(viable), 'file')} ready ({total}), "
            f"[bold red]{len(refused)} refused[/]."
        )
    else:
        console.print(f"\n{_plural(len(viable), 'file')}, {total}. [green]no problems found.[/]")

    if dry_run:
        rest = " to upload the rest" if refused else ""
        console.print(f"[yellow]nothing written.[/] re-run without --dry-run{rest}.\n")
        raise typer.Exit(1 if refused else 0)
    if not yes:
        if not typer.confirm(f"upload {_plural(len(viable), 'file')} ({total})?"):
            raise typer.Exit(1)

    written: list[str] = []
    failures: list[tuple[upload_mod.Candidate, str]] = []
    with Progress(
        TextColumn("[dim]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as bar:
        for candidate in viable:
            task = bar.add_task(candidate.name, total=candidate.size)
            try:
                written.append(
                    upload_mod.upload_one(
                        bucket,
                        candidate,
                        new_id=new_id,
                        title=title,
                        progress=lambda seen, t=task: bar.update(t, completed=seen),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim
                failures.append((candidate, f"{type(exc).__name__}: {exc}"))

    for candidate, reason in failures:
        err.print(f"[yellow]failed[/] {candidate.name}: {reason}")

    if written:
        console.print(f"\nuploaded [green]{_plural(len(written), 'file')}[/]")
        result = classify(bucket.list())
        size = index_mod.write(bucket, index_mod.build_index(result, bucket))
        console.print(f"wrote [green]index.json[/] ({human_bytes(size)})\n")

    # Typing the title while you still remember what the file was is the whole
    # reason to do this from a terminal rather than a phone. It is a
    # convenience, not a required step, so say so rather than just seizing the
    # terminal -- `add` on its own is a complete command.
    if written and edit_after and sys.stdout.isatty() and not title:
        from keepsake.tui import KeepsakeApp

        console.print(
            f"opening the editor to title {_plural(len(written), 'file')}.  "
            "[dim]--no-edit to skip, or set them later with `keepsake set`[/]\n"
        )
        KeepsakeApp([(prof.name, bucket)], only=set(written)).run()

    if refused or failures:
        raise typer.Exit(1)


def _resolve_item(wanted: str, items: list) -> tuple[object | None, str | None]:
    """Find the item a user meant. Returns (item, error).

    Full keys are long, and the thing you have in your head after an upload is
    the filename. So a bare `IMG_7900.MOV` resolves, as long as it names one
    file; an ambiguous one lists the candidates rather than picking.
    """
    for item in items:
        if item.media_key == wanted:
            return item, None

    matches = [i for i in items if i.media_key.endswith("/" + wanted)]
    if len(matches) == 1:
        return matches[0], None
    if matches:
        listed = ", ".join(i.media_key for i in matches)
        return None, f"{wanted!r} matches several files ({listed}). Use the full key."
    return None, f"no file matching {wanted!r} with a sidecar. `keepsake status` lists them."


@app.command("set")
def set_cmd(
    keys: Annotated[
        list[str], typer.Argument(help="Media keys, or filenames if unambiguous")
    ],
    profile: TargetProfileOpt = None,
    title: Annotated[Optional[str], typer.Option("--title", "-t")] = None,
    recorded_at: Annotated[
        Optional[str], typer.Option("--recorded-at", help="YYYY-MM-DD")
    ] = None,
    tags: Annotated[Optional[str], typer.Option("--tags", help="comma, separated")] = None,
    location: Annotated[Optional[str], typer.Option("--location")] = None,
    notes: Annotated[Optional[str], typer.Option("--notes")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the changes and write nothing")
    ] = False,
) -> None:
    """Set metadata on files already in a library.

    Pass an empty string to clear a field. `--title` names one file; the other
    fields can apply to several at once, which is how you tag a batch.
    """
    from keepsake.tui.library import is_spec_date, load_items, save_item

    edits = {
        "title": title,
        "recorded_at": recorded_at,
        "tags": tags,
        "location": location,
        "notes": notes,
    }
    edits = {field: value for field, value in edits.items() if value is not None}
    if not edits:
        _fail("nothing to set. Pass at least one of --title, --recorded-at, --tags, "
              "--location, --notes.")
    if title is not None and len(keys) > 1:
        _fail("--title names a single file; twenty files cannot share one title.")

    # SPEC requires this shape, and the archive should read the same forever.
    # Refusing beats writing something off-spec that has to be found later.
    if recorded_at and not is_spec_date(recorded_at):
        _fail(f"{recorded_at!r} is not a SPEC date. Use YYYY-MM-DD, or RFC 3339 with a time.")

    prof, bucket = _open_one(profile, writable=not dry_run)
    items = load_items([(prof.name, bucket)])

    chosen = []
    for wanted in keys:
        item, error = _resolve_item(wanted, items)
        if error:
            _fail(error)
        chosen.append(item)

    _header(prof)
    changed = []
    for item in chosen:
        console.print(f"  {item.media_key}")
        for field, value in edits.items():
            before = item.text(field) or "[dim]—[/]"
            item.edit(field, value)
            after = item.text(field) or "[dim]—[/]"
            mark = "" if field in item.changed else "  [dim](unchanged)[/]"
            console.print(f"      {field:<12}{before} [dim]→[/] {after}{mark}")
        if item.dirty:
            changed.append(item)

    if not changed:
        console.print("\n[green]already set[/]\n")
        return
    if dry_run:
        console.print(
            f"\n[yellow]nothing written.[/] re-run without --dry-run "
            f"to update {_plural(len(changed), 'sidecar')}.\n"
        )
        return

    for item in changed:
        save_item(item)
    result = classify(bucket.list())
    size = index_mod.write(bucket, index_mod.build_index(result, bucket))
    console.print(
        f"\nwrote [green]{_plural(len(changed), 'sidecar')}[/], "
        f"rebuilt index.json ({human_bytes(size)})\n"
    )


@app.command()
def edit(
    profile: ProfileOpt = None,
    prefix: PrefixOpt = "",
) -> None:
    """Browse every library and fill in titles, dates, tags, and notes."""
    from keepsake.tui import KeepsakeApp

    sources = [(prof.name, bucket) for prof, bucket in _open(profile, writable=True)]
    KeepsakeApp(sources, prefix=prefix).run()


if __name__ == "__main__":
    app()
