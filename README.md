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

KEEPSAKE_FAMILY_BUCKET=media-main
KEEPSAKE_FAMILY_ID=...
KEEPSAKE_FAMILY_KEY=...
```

Adding a bucket is three lines and no code. The SigV4 region is derived from
the endpoint hostname, so there is no region to get wrong. The `KEEPSAKE_`
prefix matters — discovery scans the whole environment, not just `.env`.

Profile resolution: `--profile/-p`, then `KEEPSAKE_PROFILE`, then the only
profile if there is exactly one.

## Commands

Four verbs, matching the four things you actually want to do:

| | |
|---|---|
| `keepsake profiles` | Can I reach my buckets? |
| `keepsake status` | What is in this bucket, and is it healthy? |
| `keepsake sync` | Make the bucket match the convention. |
| `keepsake edit` | Fill in titles, dates, tags, and notes. |
| `keepsake version` | |

```sh
uv run keepsake profiles --verify        # list profiles, reach each bucket
uv run keepsake status -p family         # survey + findings
uv run keepsake status -p family --files # every key
uv run keepsake sync -p family           # show every change it would make
uv run keepsake sync -p family --details # ...including full sidecar contents
uv run keepsake sync -p family --apply   # write them
uv run keepsake edit -p family           # terminal UI
```

`sync` writes a stub sidecar for any media lacking one, then rebuilds
`index.json` from every sidecar — in that order, because sidecars are the
source of truth and the catalog is derived from them. It is idempotent:
running it again writes nothing, and it skips rewriting an unchanged
`index.json` rather than creating a pointless new object version.

Adding videos to a bucket later, by any means, is followed by one command:

```sh
uv run keepsake sync -p family --apply
```

### `keepsake edit`

A list of the library on the left, a form on the right. Arrow through, type,
save.

```
┌─ media-main ─────────────────────┬─ IMG_0002.MOV ────────┐
│ ● 2026/05/IMG_0002.MOV   —      62MB │ title       [       ] │
│   2026/05/IMG_0007.MOV   Recital     │ recorded_at [       ] │
│                                      │ tags        [       ] │
│ 1 of 4 titled                        │ location    [       ] │
└──────────────────────────────────────┴───────────────────────┘
```

Navigate entirely with arrows: `up`/`down` through the list, `right` into the
form, `up`/`down` between fields, `left` at the start of a field back to the
list. `escape` returns to the list from anywhere.

| Key | |
|---|---|
| `o` | Open the selected video in your system player |
| `u` | Show only untitled items |
| `ctrl+s` | Save |
| `ctrl+q` | Save and quit |
| `escape` | Back to the list |

The bare letters act only from the list — a focused field consumes printable
keys, so typing "out" in a title stays text. `ctrl+o` works from anywhere.
There is deliberately no `ctrl+u`: `Input` binds it to delete-to-start.

`o` matters more than it looks: you cannot title `IMG_0002.MP4` without
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
does not leave a trail of catalog versions.

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
