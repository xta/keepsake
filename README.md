# keepsake

A CLI for managing [keepsake](SPEC.md) libraries in object storage.

**[SPEC.md](SPEC.md) is the convention.** It is the authority, it is
implementation-agnostic, and it never mentions this tool. This repo also holds
one implementation of it, in Python. Tested against Backblaze B2.

## Safety model

> The write surface is exactly three things: the root `index.json`,
> `{media}.json` sidecars, and `{media}.{jpg,png,webp}` thumbnails.
> **Everything else in the bucket is media and is read-only.**

Enforced at one chokepoint in `storage/base.py`: `put()` and `delete()` reject
any key that isn't a companion, unless the caller passes `allow_media=True`,
which no command sets. No other code path can reach a media file.

Back that up at the credential layer — see key capabilities below. Two
independent layers, and the one B2 enforces is the one that actually matters.

This means the tool implements a deliberate **subset** of SPEC.md's
"Delete order": steps 1–2 (sidecar, thumbnail) yes, step 3 (the media file)
never.

Commands that write take `--apply`. Without it they print exactly what they
would do and touch nothing.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
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

Five verbs, matching the things you actually want to do:

| | |
|---|---|
| `keepsake profiles` | Can I reach my buckets? |
| `keepsake status` | What is in my libraries, and are they healthy? |
| `keepsake sync` | Make them match the convention. |
| `keepsake edit` | Fill in titles, dates, tags, and notes. |
| `keepsake version` | |

```sh
uv run keepsake profiles --verify   # list profiles, reach each bucket

uv run keepsake status              # survey + findings, every library
uv run keepsake sync                # show every change it would make
uv run keepsake sync --apply        # write them
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

### `keepsake edit`

Every library in one list on the left, a form on the right. Arrow through,
type, save. With more than one library open, a `library` column shows which
bucket each video lives in, and a save goes back to that bucket.

The `length` column shows the runtime when the sidecar records `duration_s`,
and falls back to file size — dimmed, so the two read apart — when it does
not. Nothing populates `duration_s` yet, so in practice it shows sizes.

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
