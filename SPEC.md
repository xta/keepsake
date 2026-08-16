# keepsake

A convention for storing family videos in object storage, with metadata that lives alongside the files.

No database. No server required. The bucket is the entire system.

## Why

Cloud photo services charge steadily for storage you don't control, and their metadata lives in their systems. Object storage (AWS S3, Cloudflare R2, Backblaze B2, etc.) is cheap and provider-agnostic, but a bucket full of `IMG_4471.mp4` is not an archive.

keepsake defines a small layout convention that makes a bucket self-describing.

## Non-goals

- **No external datastore.** Nothing outside the bucket may be required to read or interpret its contents.
- **No required server.** A client with read credentials and `index.json` is sufficient to browse.
- **Not a sync tool.** Transport is an upload client, CLI command, or anything else.
- **Not a transcoder.** Files are stored as uploaded.
- **Not a shared bucket.** A keepsake bucket holds a keepsake library and nothing else. Every key that isn't `index.json` and carries a file extension is treated as media or a companion. An unrelated file therefore classifies as media with no sidecar, and stays out of the catalog until one is written for it. Use a dedicated bucket.

## Layout

```
bucket/
  index.json
  media/
    2026/
      piano-recital.mp4
      piano-recital.mp4.json
      piano-recital.mp4.jpg
      vacation-day1.mp4
      vacation-day1.mp4.json
```

A media file may have two companions:

| File | Role |
|---|---|
| `{filename}` | The media file. |
| `{filename}.json` | **Sidecar.** Metadata. The source of truth. |
| `{filename}.jpg` | **Thumbnail.** Derived, optional, regenerable. |

Companions are named by appending a suffix to the **complete filename**; not by replacing its extension. The sidecar for `piano-recital.mp4` is `piano-recital.mp4.json`.

This makes the mapping total and unambiguous. `vacation.mp4` and `vacation.mov` can coexist in one directory.

**Media filenames carry an accurate extension.** Every media key ends in an extension naming its format — `.mov`, `.mp4`, `.jpg`, `.heic`. Writers must produce one; readers depend on it. It is what separates `vacation.jpg`, which is media, from `piano-recital.mp4.jpg`, which is a thumbnail.

A key is media only when its final path segment does not begin with `.` and contains a `.`. `IMG_0002.MOV` qualifies; `README` has no extension. A leading dot marks a file as hidden by convention, so `.bzEmpty` and `.DS_Store` are never media — nor is `.hidden.mp4`, where the leading dot outranks the extension.

"Accurate" means the extension names the right kind of file: a `.mov` holds video, a `.jpg` holds an image. It does not require distinguishing between closely related containers. `.mp4` and `.mov` are both reasonable names for ISO base media format, and a reader must not treat that as an error.

**A reader must never inspect file contents to determine format.** The extension is the answer. A key that is not media by the rule above is not part of the library: report it so it stays visible, but do not catalogue it.

**Naming is authoritative.** A key formed by appending a known suffix to an existing media key is that file's companion, not standalone media.

**Suffix case is insignificant.** Companion suffixes match case-insensitively. `IMG_0002.MOV.JSON` and `IMG_0002.MOV.json` are both sidecars for `IMG_0002.MOV`. Cameras and phones vary in the case they emit, and a library should not fracture over it.

Object storage keys are case-sensitive, so `clip.mov` and `clip.MOV` are genuinely two different objects, and companion resolution matches the media portion of a key exactly.

**A library must not contain two keys differing only in case.** Nothing in object storage prevents it, but no filesystem the archive is likely to be copied to can represent both — macOS and Windows are case-insensitive by default, so downloading such a library silently collapses one file onto the other. Report the collision; do not attempt to resolve it.

Case is likewise insignificant when reading a media file's extension to determine format: `IMG_0002.MOV` is QuickTime.

Writers emit lowercase suffixes. If two companions of the same kind differ only in suffix case, the library is ambiguous: report it rather than choosing one.

**Paths are arbitrary.** There is no required directory structure. The `media/` prefix and date directories above are conventional, not required. Media may sit at the bucket root or anywhere else. An existing bucket of videos becomes a keepsake bucket by adding sidecars, with no reorganization.

### Reserved key

Exactly one key is reserved: `index.json` at the bucket root. Everything else in the bucket is media, a sidecar, or a thumbnail.

A `.json` file at any other path, including a nested `index.json`, is an ordinary sidecar.

## Sidecar

One JSON file per media file, named `{filename}.json`. This is the source of truth.

```json
{
  "schema": 1,
  "id": "01a0098c-ebfd-7e9f-bac0-ca39f3495b09",
  "file": "piano-recital.mp4",
  "title": "Spring Recital",
  "recorded_at": "2026-04-12",
  "uploaded_at": "2026-04-14T02:11:09Z",
  "tags": ["piano", "school"],
  "location": "Roosevelt Elementary",
  "notes": "Second half of the program",
  "duration_s": 412,
  "size_bytes": 891234567,
  "media_type": "video/mp4",
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "thumbnail": "piano-recital.mp4.jpg"
}
```

### Required

| Field | Type | Notes |
|---|---|---|
| `schema` | integer | Format version. Currently `1`. |
| `id` | string | Stable identity for this media file. Never changes, even if the file is renamed or moved. Opaque: readers must not parse it. Writers should emit a UUID version 7 ([RFC 9562](https://www.rfc-editor.org/rfc/rfc9562)); earlier libraries emitted ULIDs, and both remain valid. |
| `file` | string | Filename relative to the sidecar's own directory. Advisory; see Key vs. contents. |
| `uploaded_at` | string | RFC 3339 timestamp. |

### Optional

| Field | Type | Notes |
|---|---|---|
| `title` | string | Human-readable name. Strongly encouraged. |
| `recorded_at` | string | `YYYY-MM-DD`, or RFC 3339 if time is known. |
| `tags` | array of string | Freeform. |
| `location` | string | Freeform. |
| `notes` | string | Freeform. |
| `duration_s` | number | Seconds. |
| `size_bytes` | integer | |
| `media_type` | string | IANA media type, e.g. `video/mp4`. A convenience so clients need not carry an extension-to-type table. The extension is authoritative; if the two disagree, the extension wins and the sidecar should be corrected. |
| `sha256` | string | Lowercase hex digest of the media file. Enables integrity checking. |
| `thumbnail` | string | Filename relative to the sidecar's directory. |

### Key vs. contents

The sidecar's key determines which media file it describes. `x.mp4.json` describes `x.mp4`, always.

The `file` field is advisory, present for readability rather than authority. If it disagrees with the key, the key wins and the sidecar should be corrected.

### Unknown fields must be preserved

A writer that does not recognize a field must carry it through unchanged on write. This lets clients of different versions coexist without coordination.

## Thumbnails

A thumbnail is a still image for a media file, named `{filename}.jpg` (or `.png`, `.webp`).

The naming is authoritative: a key formed by appending an image extension to an existing media key is that file's thumbnail, not standalone media.

When the media is itself an image, the extension doubles: `img3.jpg.jpg` is the thumbnail of `img3.jpg`, and `img3.png.jpg` the thumbnail of `img3.png`. This looks like a mistake and is not one. The suffix is appended to the complete filename without exception, because a rule with exceptions stops being total.

The sidecar's `thumbnail` field records which extension exists, so clients reading `index.json` don't have to probe.

Thumbnails are optional and derived. Nothing breaks without one, and losing one costs a re-render, not information.

## index.json

A derived catalog at the bucket root. Disposable. Regenerate it by listing the bucket and collecting sidecars.

```json
{
  "generated_at": "2026-07-22T18:03:11Z",
  "count": 2,
  "items": [
    { "path": "media/2026/piano-recital.mp4", "...": "full sidecar contents inlined" }
  ]
}
```

Each entry is the complete sidecar plus a `path` field giving the media file's full key from the bucket root. Sidecar contents are inlined rather than referenced so a viewer needs exactly one fetch to render a library.

Every field is derived from the bucket's contents. There is no bucket-level metadata — a client that wants to label a library uses the bucket name or its own settings. Federation across buckets is not specified here.

`items` is sorted by `path`, ascending. This is a stability guarantee, not a display order. It keeps regenerated indexes stable and cacheable across rebuilds. Display order is up to the client.

`index.json` contains no information that is not derivable from the bucket. Delete it, reindex, and nothing is lost. A stale `index.json` is a cosmetic bug, not data loss.

### Reindexing

List the entire bucket, excluding the root `index.json`. Classify in this order:

1. **Sidecars.** Every key ending in `.json` is a sidecar. Stripping that suffix yields the media key it describes.
2. **Thumbnails.** Every key formed by appending an image extension to another key present in the bucket is that key's thumbnail.
3. **Media.** Everything remaining that carries a file extension is media. Media with no sidecar is unindexed. Surface it, don't hide it.

A remaining key with no extension is not media and is not catalogued. Report it; do not guess at its type.

Each step reads the set of keys present, not the results of the step before it. Classification describes what each key is, not whether its item is complete: a thumbnail is recognised as a thumbnail before its media has a sidecar, which keeps a bucket freshly filled by an upload tool from counting derived files as library items. The media itself stays unindexed until its sidecar is written.

This is what the extension requirement buys. `a.jpg` is unambiguously media, because a file named `a` could not be media.

A sidecar whose media key does not exist is a `Sidecar, no media` failure. Report it, don't index it.

### Incremental updates

A full rebuild is not required after every write. A writer that trusts the current `index.json` may insert, replace, or remove a single entry at its sorted position and update `generated_at` and `count`.

Full rebuilds are for repair, and for buckets modified by other means.

## Write order

1. Upload the media file
2. Upload the thumbnail, if any
3. Write the sidecar
4. Regenerate `index.json` (may be deferred)

**The sidecar is the commit marker.** Writing it last means a sidecar can never reference a file that isn't there. The reverse, a media file with no sidecar, is an expected intermediate state, and clients should surface such files as untitled rather than hiding them.

## Delete order

1. Delete the sidecar
2. Delete the thumbnail, if any
3. Delete the media file
4. Regenerate or update `index.json`

Interrupting this leaves media with no sidecar, which is unindexed, recoverable, and already an expected state. Deleting media first would leave a sidecar pointing at nothing.

## Rename and move

`id` never changes. The key may.

If a media file is renamed or moved, its companions move with it, since companion keys are derived from the media key. Update the sidecar's `file` field to match, and reindex.

## Failure modes

| State | Meaning | Recovery |
|---|---|---|
| Media, no sidecar | Upload interrupted, or uploaded by other means | Generate a stub sidecar from object metadata |
| Sidecar, no media | Should be unreachable under the write order | Report; delete sidecar or restore file |
| Key with no extension | Uploaded by a tool that strips it, or renamed by hand | Not catalogued. Report; rename to add the correct extension |
| Keys differing only in case | Two uploads of the same file from different sources | Report; rename one. Not recoverable once copied to a case-insensitive filesystem |
| Missing thumbnail | Normal; `thumbnail` is optional | Generate later, or leave |
| Stale `index.json` | Normal after any write | Regenerate |

No failure mode loses a video. That's the property the layout is built around.

## Concurrency

Sidecar writes are last-writer-wins.

The unsafe window is the entire edit session, not a few seconds. A client that loads a sidecar, waits while someone types, then PUTs will clobber anything written in between.

Writers should therefore re-read the sidecar immediately before writing and merge field-by-field, rather than PUTting an object loaded earlier. This narrows the window to the duration of a single request. It does not close it.

For a family archive this is an accepted tradeoff. A lost edit costs a retyped title, not a video.

## Bucket setup

If your provider supports object versioning, configure it to limit retained versions. Sidecars are rewritten on every metadata edit, and a library edited over years accumulates thousands of tiny JSON revisions that quietly cost money.

## License

MIT


