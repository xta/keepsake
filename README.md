# keepsake

A convention for storing family videos in object storage, with metadata that
lives alongside the files.

No database. No server required. The bucket is the entire system.

Cloud photo services charge steadily for storage you don't control, and the
metadata you type into them stays in their systems. Object storage is cheap and
provider-agnostic — but a bucket full of `IMG_4471.mp4` is not an archive.
keepsake is the small set of rules that turns one into an archive: every video
gets a JSON file beside it, and a catalog at the root ties them together. Both
are plain files in the bucket, readable by anything, outliving any particular
tool.

## The convention

**[SPEC.md](SPEC.md) is the whole thing.** It's short, it's the authority, and
it never mentions any particular tool or storage provider. If you only read one
file here, read that one.

## Implementations

| | |
|---|---|
| **[`cli/`](cli/)** | Python command line and terminal UI. Survey a bucket, adopt existing videos, upload new ones, fill in titles. |

That's the only one so far. Others would sit beside it.

## When the code and the spec disagree

**The spec is right and the code has a bug.** That's the direction it goes,
always.

`cli/` is an example of how to implement the convention, not a definition of
it. It's the tool that happens to exist, written by the person who happened to
need it first, and it implements a deliberate subset — it never deletes a
video, for instance, though SPEC.md describes how deletion should work.

So don't read the Python to learn the format, and never edit SPEC.md to match
what the code does. Anyone should be able to write their own client from the
spec alone and have it interoperate with this one — that's the property worth
protecting, and it survives exactly as long as the spec stays the authority.

## License

MIT
