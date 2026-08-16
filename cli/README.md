# keepsake — command line and terminal UI

A Python client for [keepsake](../SPEC.md) libraries in object storage.

**[../SPEC.md](../SPEC.md) is the convention, and it is the authority.** It is
implementation-agnostic and never mentions this tool. This is one way to
implement it, not the definition of it — where the two disagree, the spec is
right and this is the bug.

Tested against Backblaze B2. Nothing in the convention requires it; the storage
backend is one file (`src/keepsake/storage/b2.py`), and everything else talks to
the `Bucket` protocol beside it.

Run everything from this directory — `uv` and the `.env` holding your
credentials both live here.

## Safety model

> **This tool may create new media. It may never overwrite or delete it.**
> Everything else it writes is one of three things: the root `index.json`,
> `{media}.json` sidecars, and `{media}.{jpg,png,webp}` thumbnails.

Enforced at one chokepoint in `storage/base.py`. `put()` and `delete()` reject
any key that isn't a companion, unless the caller passes `allow_media=True`,
which no command sets. `put_media()` is the single door to a media key, and it
opens one way: it refuses a key that already exists, so a filename collision is
an error rather than a silent loss. No other code path can reach a media file.

Back that up at the credential layer — see key capabilities below. Two
independent layers, and the one B2 enforces is the one that actually matters.

This means the tool implements a deliberate **subset** of SPEC.md's
"Delete order": steps 1–2 (sidecar, thumbnail) yes, step 3 (the media file)
never.

`sync` writes only with `--apply`. Without it it prints exactly what it would
do and touches nothing. `add` names the files you meant, so it inverts that:
it shows the plan, asks once, and takes `--dry-run` to stop at the plan.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
cd cli
uv sync --group dev
cp .env.example .env   # then fill it in
uv run keepsake profiles --verify
```

### Backblaze B2 keys

Create **one application key per bucket**, restricted to that bucket, with
capabilities `listFiles`, `readFiles`, `writeFiles`.

**Never grant `deleteFiles`.** It is not needed: replacing a sidecar or
regenerating a thumbnail is an overwrite, not a delete. Withholding it makes
media deletion impossible at the credential layer, not merely unimplemented.

Keys are immutable, so widening a key's capabilities means issuing a new one
and swapping the values in `.env`.

### Profiles

`.env` is the profile registry. Each `KEEPSAKE_<NAME>_BUCKET` defines a
profile named `<name>` in lowercase:

```sh
KEEPSAKE_ENDPOINT=https://s3.us-east-001.backblazeb2.com

KEEPSAKE_JANE_BUCKET=media-jane
KEEPSAKE_JANE_ID=...
KEEPSAKE_JANE_KEY=...
```

Adding a bucket is three lines and no code. The SigV4 region is derived from
the endpoint hostname, so there is no region to get wrong. The `KEEPSAKE_`
prefix matters — discovery scans the whole environment, not just `.env`.

A profile is just a bucket, so name them however suits you. One per person is
a natural fit — SPEC.md gives each library its own bucket, and a bucket-scoped
B2 key per profile means one person's credentials cannot reach another's
videos.

**Every command acts on all profiles unless you name one.** An archive is
usually several buckets, and "all of them" is the common intent; `-p jane`
narrows it to one.

## Commands

A verb for each thing you actually want to do:

| | |
|---|---|
| `keepsake profiles` | Can I reach my buckets? |
| `keepsake status` | What is in my libraries, and are they healthy? |
| `keepsake sync` | Make them match the convention. |
| `keepsake add` | Put new files in. |
| `keepsake set` | Fill in titles, dates, tags, and notes. |
| `keepsake edit` | ...or the same, in a terminal UI. |
| `keepsake version` | |

**Either front end finishes the job on its own.** Pick whichever suits:

```sh
# all shell, never opens a UI
uv run keepsake add ~/transfers/*.mov -p rex --no-edit
uv run keepsake set recital.mov -p rex --title "Spring Recital" --tags piano,school

# all TUI: press `a` to upload, then type the titles in place
uv run keepsake edit -p rex
```

`add` ends by opening the editor on what it just wrote, because a title is
easiest to type while you still remember what the file was. That is a
convenience, not a step — `--no-edit` skips it, and giving `--title` skips it
too.

```sh
uv run keepsake profiles --verify   # list profiles, reach each bucket

uv run keepsake status              # survey + findings, every library
uv run keepsake sync                # show every change it would make
uv run keepsake sync --apply        # write them
uv run keepsake add clip.mov -p rex # upload, with a sidecar
uv run keepsake set clip.mov -p rex -t "Title"   # metadata from the shell
uv run keepsake edit                # terminal UI over every library

uv run keepsake status -p jane      # ...or narrow any of them to one
uv run keepsake sync -p jane --details
```

`sync` writes a stub sidecar for any media lacking one, then rebuilds
`index.json` from every sidecar — in that order, because sidecars are the
source of truth and the catalog is derived from them. It is idempotent:
running it again writes nothing, and it skips rewriting an unchanged
`index.json` rather than creating a pointless new object version.

Adding videos to any bucket later, by any means, is followed by one command:

```sh
uv run keepsake sync --apply
```

### `keepsake add`

Uploads files that did not arrive by other means — digitised home movies,
camcorder transfers, DSLR footage. Phone video is already handled by whatever
puts it in the bucket; `sync` adopts that.

```sh
uv run keepsake add ~/Movies/recital.mov -p rex -t "Spring Recital"
uv run keepsake add ~/transfers/*.mov -p rex          # a batch
uv run keepsake add tape.mov -p rex --into home-movies
uv run keepsake add tape.mov -p rex --dry-run         # plan only
```

Files land in **`YYYY/MM/` taken from the video's own recording date**, read
out of the QuickTime/MP4 header. A tape digitised today but shot in 2019 is
filed under `2019/03/`, not under this month. The same header supplies
`duration_s`, so the `length` column starts showing runtimes.

`--into` overrides the layout. `--into /` puts files at the bucket root, which
is allowed but warned about — a root full of loose videos next to `index.json`
is not something anyone chooses on purpose.

Every refusal happens in the plan, before a byte moves, and is printed beside
the files that will upload. The plan ends with a verdict rather than leaving
you to infer one from the absence of red:

```
$ keepsake add ~/transfers/*.mov -p rex --dry-run

rex -> feng-media-rex

  + 2019/03/recital.mov     1.2 GB   6:52  recorded 2019-03-07
  + 2026/08/IMG_7901.MOV   21.9 MB   0:15  no date in file, filed under today
  ! wedding-4k.mov
      6.4 GB, over the 5 GB single-upload limit. keepsake uploads in one
      request, so this file cannot be sent as-is -- split or transcode it first

2 files ready (1.2 GB), 1 refused.
nothing written. re-run without --dry-run to upload the rest.
```

Each row says where its date came from, because otherwise the two `2026/08/`
cases are indistinguishable: a video actually shot this month, and a video
whose header held no date so today's was used. Only the second is worth a
second look. With no refusals the plan ends `no problems found.` and exits 0.

Refused for: no file extension (SPEC requires one), a key already taken, a key
differing from an existing one only in case, a name shaped like a companion
key, or over the ceiling. One bad file never stops the rest, and the exit code
is non-zero if anything was refused.

`add` writes to exactly one library, so `-p` is required when you have several.
It and `set` are the exceptions to the "all libraries by default" rule — for a
command that writes, omitting the flag is an error rather than an instruction.

After a successful upload it opens the editor on exactly what it just wrote, so
you can type the titles while you still remember what the files were. That is a
convenience, not a step: `--no-edit` skips it, giving `--title` skips it, and
`keepsake set` can fill the same fields later from the shell.

### `keepsake set`

The shell half of metadata editing, so an upload never has to hand off to a UI.

```sh
uv run keepsake set recital.mov -p rex --title "Spring Recital"
uv run keepsake set recital.mov tape2.mov -p rex --tags camcorder-transfer
uv run keepsake set recital.mov -p rex --title ""        # clear a field
```

```
rex -> feng-media-rex

  2019/03/recital.mov
      title       — → Spring Recital
      tags        — → piano, school

wrote 1 sidecar, rebuilt index.json (957 B)
```

A bare filename resolves to its key as long as it names one file; an ambiguous
one lists the candidates instead of guessing. `--title` names a single file,
since twenty files cannot share one title; the other fields apply to as many as
you list, which is how you tag a batch.

An empty string clears a field, removing it from the sidecar rather than
writing a null. An off-spec `--recorded-at` is refused outright — SPEC requires
`YYYY-MM-DD`, and the archive should read the same everywhere, forever.

Writes go through the same merge-on-save as the TUI: the stored sidecar is
re-read and only the fields you named are applied, so a concurrent edit to some
other field survives.

### `keepsake edit`

Every library in one list on the left, a form on the right. Arrow through,
type, save. With more than one library open, a `library` column shows which
bucket each video lives in, and a save goes back to that bucket.

Press `a` to upload from inside the editor. Drag files from Finder straight
into the terminal — they paste as quoted paths, which the dialog understands,
along with `~` and globs. The destination field defaults to the dated layout,
shows the prefixes your library already uses, and warns if you point it at the
bucket root.

The `length` column shows the runtime when the sidecar records `duration_s`,
and falls back to file size — dimmed, so the two read apart — when it does
not. `add` fills `duration_s` from the file's header; videos adopted by `sync`
have no runtime recorded yet, so those rows still show sizes.

```
┌─ 2 libraries ────────────────────────────┬─ IMG_0002.MOV ──────────┐
│ ● jane  IMG_0002.MOV   3:42  Spring play │ title       [       ]   │
│   jane  IMG_0007.MOV  62 MB  —           │ recorded_at [       ]   │
│   john  IMG_0011.MOV 240 MB  —           │ tags        [       ]   │
│ 1 of 3 titled                            │ location    [       ]   │
└──────────────────────────────────────────┴─────────────────────────┘
```

Navigate entirely with arrows: `up`/`down` through the list, `right` into the
form, `up`/`down` between fields, `left` at the start of a field back to the
list. `escape` returns to the list from anywhere.

| Key | |
|---|---|
| `o` | Open the selected video in your system player |
| `u` | Show only untitled items |
| `ctrl+s` | Save |
| `q` | Quit — offers save, discard, or cancel if anything is unsaved |
| `ctrl+q` | Save and quit, without asking |
| `escape` | Back to the list |

`q` only interrupts when leaving would lose work; with nothing pending it just
exits. Discarding still rebuilds `index.json` if you saved earlier in the
session, since those writes are already on the bucket.

The bare letters act only from the list — a focused field consumes printable
keys, so typing "out" in a title stays text. `ctrl+o` works from anywhere.
There is deliberately no `ctrl+u`: `Input` binds it to delete-to-start.

Fields that have a required shape say so, beside the label and as the
placeholder, and `recorded_at` turns red when what you typed is not
`YYYY-MM-DD`. SPEC fixes that format for a reason — `03/04/2026` means two
different days depending on who wrote it — so the field says which one it
wants rather than accepting anything and producing an unreadable archive.

`o` matters more than it looks: you cannot title `IMG_0002.MOV` without
watching it. It signs a short-lived URL and hands it to the system player,
which streams the video without downloading it.

**Saving re-reads before it writes.** SPEC.md notes that sidecar writes are
last-writer-wins and the unsafe window is the whole edit session — someone who
loads a sidecar, types for two minutes, then PUTs the object they started with
would silently discard anything written meanwhile. So on save the stored
sidecar is fetched again and only the fields edited in this session are applied,
narrowing the window to a single request. B2's S3 API has no conditional
writes, so it cannot be closed entirely.

`index.json` is rebuilt once on quit, not on every save, so a session of edits
does not leave a trail of catalog versions. Only libraries you actually wrote
to are rebuilt.

### What `sync` records in a new sidecar

Only what the bucket already knows: `schema`, a fresh ULID `id`, `file`,
`uploaded_at` (the object's own timestamp), `size_bytes`, and `media_type`.

`title` and `recorded_at` are left absent rather than derived from the filename
or path. A path like `2026/05/IMG_0002.MOV` implies a year and a month, but
SPEC.md requires `YYYY-MM-DD`, and inventing a day would put a fact in the
archive that nobody established. An absent field is easy to fill in later; a
wrong one looks authoritative forever.

`add` has the file itself rather than just a listing, so it records more:
`sha256` (computed on a second local read — nearly free now, expensive forever
after), plus `recorded_at` and `duration_s` when the header supplies them.
`title` is still the one field only a person can fill.

## Backblaze notes

Both live in `storage/b2.py`:

- **Checksums.** Since boto3 ~1.36 the AWS SDKs send
  `x-amz-sdk-checksum-algorithm` by default and B2 rejects it. Clients are
  built with `request_checksum_calculation="when_required"`. s3transfer does
  not reliably honour this on the managed upload path
  ([boto/s3transfer#327](https://github.com/boto/s3transfer/issues/327)); the
  small `put_object` writes used here are unaffected.
- **Versioning.** B2 retains every file version unless a lifecycle rule says
  otherwise, and sidecars are rewritten on every metadata edit. Set each
  bucket's Lifecycle Settings to *"Keep only the last version of the file"*.
  `keepsake status` reports this.

## Development

```sh
uv run pytest
```

The suite runs entirely against `LocalDirBucket` — no network, no credentials,
no B2. Fixture buckets are just directory trees.

## License

MIT
