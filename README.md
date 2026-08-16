# keepsake

A convention for organizing your media files in buckets you own, with metadata
that lives alongside the files.

No database. No server required. The bucket is the entire system.

Your originals are kept exactly as uploaded, and every file sits beside a plain
JSON file describing it — readable by anything, long after this tool is gone.
A bucket full of `IMG_4471.mp4` is not an archive. These are the rules that make
it one.

## The convention

**[SPEC.md](SPEC.md)** is the authority.

## Implementations

| | |
|---|---|
| **[`cli/`](cli/)** | Python command line and terminal UI. Survey a bucket, adopt existing videos, upload new ones, fill in titles. |

These are sample implementations. Where an implementation and the spec disagree,
the spec is right and the code has a bug.

## License

MIT
