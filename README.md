# keepsake

A CLI for managing [keepsake](SPEC.md) libraries in object storage.

**[SPEC.md](SPEC.md) is the convention.** It is the authority, it is
implementation-agnostic, and it never mentions this tool. This repo also holds
one implementation of it, in Python. Tested against Backblaze B2.

## Status: phase 1, read-only

The tool does not write anything to a bucket yet. Buckets are opened read-only
and the storage layer refuses writes regardless of what a command asks for.

Phase 1 answers "what is actually in these buckets, and what would adopting the
convention involve" — which is the useful question when your buckets are still
just folders full of `IMG_4471.mov`.

## Safety model

> The write surface is exactly three things: the root `index.json`,
> `{media}.json` sidecars, and `{media}.{jpg,png,webp}` thumbnails.
> **Everything else in the bucket is media and is read-only.**

Enforced at one chokepoint in `storage/base.py`: `put()` and `delete()` reject
any key that isn't a companion, unless the caller passes `allow_media=True`,
which only an explicit user-invoked delete command will ever set. No other code
path can reach a media file.

Back that up at the credential layer — see key capabilities below. Two
independent layers, and the one B2 enforces is the one that actually matters.

This means the tool deliberately implements a **subset** of SPEC.md's
"Delete order": steps 1–2 (sidecar, thumbnail) yes, step 3 (the media file)
only on explicit invocation. That divergence is intentional.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync --group dev
cp .env.example .env   # then fill it in
uv run keepsake profiles --verify
```

### Backblaze B2 keys

Create **one application key per bucket**, restricted to that bucket:

| Phase | Capabilities |
|---|---|
| Now (read-only) | `listFiles`, `readFiles` |
| Phase 2 (writes) | `listFiles`, `readFiles`, `writeFiles` |
| Ever | **never** `deleteFiles` |

B2 application keys are immutable — you cannot add a capability to an existing
key, so moving to phase 2 means issuing new keys and swapping the values in
`.env`. That is a feature: read-only keys today mean the tool provably cannot
alter your originals while you are still testing it.

`deleteFiles` is never needed. Replacing a sidecar or regenerating a thumbnail
is an overwrite (`writeFiles`), not a delete.

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

```sh
uv run keepsake profiles --verify        # list profiles, reach each bucket
uv run keepsake ls -p family             # survey: extensions, prefixes, sizes
uv run keepsake ls -p family --files     # every key
uv run keepsake check -p family          # SPEC failure modes + B2 lifecycle
uv run keepsake reindex -p family        # build index.json, print to stdout
uv run keepsake reindex -p family -o out.json   # ...or to a local file
```

`reindex` never writes to the bucket in phase 1. `-o` writes a local file only.

## Backblaze notes

Both of these live in `storage/b2.py`:

- **Checksums.** Since boto3 ~1.36 the AWS SDKs send
  `x-amz-sdk-checksum-algorithm` by default and B2 rejects it. Clients are
  built with `request_checksum_calculation="when_required"`. Note that
  s3transfer does not reliably honour this on the managed upload path
  ([boto/s3transfer#327](https://github.com/boto/s3transfer/issues/327)) —
  verify before phase 3 builds on `upload_file`.
- **Versioning.** B2 retains every file version unless a lifecycle rule says
  otherwise, and sidecars are rewritten on every metadata edit. Set each
  bucket's Lifecycle Settings to *"Keep only the last version of the file"*.
  `keepsake check` reports this.

## Roadmap

- **Phase 2** — writes: real `reindex`, `adopt` (stub sidecars from object
  metadata), `edit` with re-read-and-merge.
- **Phase 3** — `ffprobe` for `duration_s`, thumbnail generation, `sha256`.
  Requires `ffmpeg`.
- **Phase 4** — TUI for metadata entry, which is the interface this whole tool
  exists to support.

## Development

```sh
uv run pytest
```

The suite runs entirely against `LocalDirBucket` — no network, no credentials,
no B2. Fixture buckets are just directory trees.

## License

MIT
