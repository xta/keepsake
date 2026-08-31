# keepsake — web

A multi-user web app for browsing and streaming a [keepsake](../SPEC.md)
library: sign in, connect the buckets you hold credentials for, and watch your
videos.

This is a **second implementation of the convention, written from
[SPEC.md](../SPEC.md)** rather than ported from [`cli/`](../cli). The two share
no code on purpose. Where an implementation and the spec disagree, the spec
wins.

Nothing here is specific to any person, bucket, or provider. You supply your
own credentials; the app stores them encrypted and talks to your bucket.

## How it works

- **Reads `index.json`, never lists the bucket.** SPEC makes the catalog a
  derived document with every sidecar inlined, precisely so a viewer needs one
  request instead of a listing plus N sidecar fetches.
- **Caches that catalog in Postgres** so the grid can sort and paginate without
  re-parsing a whole document on every page view. The cache is refreshed on
  first view, after a short TTL, and on demand; an unchanged catalog costs one
  conditional request thanks to ETags. **It is a cache and never a source of
  truth** — drop the tables, refetch, lose nothing. The bucket is the system.
- **Streams with presigned URLs; the app never proxies bytes.** Video goes
  bucket-to-browser, so seeking works and no request thread is held for the
  length of a film. Media URLs are signed for 12 hours because SigV4 checks
  expiry on every range request, and a shorter window kills a long video
  mid-watch.
- **Never transcodes.** Files are served exactly as uploaded, per SPEC. A
  format the browser cannot play gets a thumbnail and a download button.

## Requirements

- Ruby (see [`.ruby-version`](.ruby-version))
- PostgreSQL
- Node.js and npm, for the Vite build

## Running it locally

```sh
bin/setup --skip-server     # gems, npm packages, database
bin/rails keepsake:invite   # prints a claim link
bin/dev                     # Rails on :3000, Vite alongside it
```

Open the claim link, create your account, and you are in. (Plain `bin/setup`
also works, but it starts the server itself, so mint the invitation from a
second terminal.)

### Trying it without any credentials

The repo ships a small fixture library — a handful of real video files, their
sidecars, and an `index.json` — so you can see the whole app work offline:

```sh
bin/rails keepsake:demo      # creates a demo account + attaches the fixtures
```

Nothing is ever seeded automatically: `db/seeds.rb` is empty, and this task
refuses to run outside development or test. `bin/rails keepsake:undemo` removes
what it made. To attach the fixtures to an account you already have, use
`bin/rails keepsake:demo_library` instead.

The fixture library uses the `local`
provider, a directory backend that implements the same interface as the S3 one.
It exists so the app is developable and testable with no network and no
credentials, and it deliberately covers the awkward cases: an untitled file, a
video with no thumbnail, an unplayable `.avi` that *has* a thumbnail, and a
HEIC that has none.

The `local` provider is only selectable in development and test.

## Connecting a real bucket

Pick your provider and the form asks only for what that provider needs. Presets
build the endpoint themselves, so you never hand-assemble one.

| Provider | You supply |
|---|---|
| Amazon S3 | region, bucket |
| Backblaze B2 | region (the middle part of your S3 endpoint), bucket |
| Cloudflare R2 | account id, bucket |
| Other S3-compatible | endpoint, region, bucket |

**Use a read-only key scoped to one bucket.** Viewing needs nothing more, and
it means a breach of this app cannot damage your archive. The form links to how
per provider.

If a bucket has no `index.json`, the app says so and points at
`keepsake sync --apply` rather than showing an empty grid.

## Security notes

Every account holds live object-storage credentials, which shapes several
decisions:

- **Signup is invite-only.** There is no open registration form. Invitations
  are single-use and expire; mint them with `bin/rails keepsake:invite` and
  list them with `bin/rails keepsake:invites`.
- **Secrets are encrypted at rest** with Active Record Encryption
  (non-deterministic), never rendered back to the browser, and never included
  in a page's props. The edit form shows a masked hint; leaving the field blank
  keeps the stored key.
- **Endpoints are validated before every request.** A user-supplied endpoint is
  a URL this server will connect to, so `Keepsake::EndpointGuard` requires
  https and refuses anything resolving to a private, loopback, link-local or
  otherwise reserved address — including IPv4-mapped IPv6 forms. Read the
  comments there: a TOCTOU window remains, and egress filtering on the host is
  the real fix.

## Tests

```sh
bin/rails test
```

The suite runs entirely against the fixture library. No network, no
credentials. `test/lib/keepsake/` asserts the SPEC rules directly — key
classification, companion naming, the thumbnail-versus-media distinction — and
those assertions come from the spec, not from reading the Python.

## Deploying your own instance

Deployment uses [Kamal](https://kamal-deploy.org). **This repo contains no
deployment specifics** — no servers, domains, registry accounts, or keys — and
must stay that way, so that cloning it and deploying your own instance is the
normal path.

- `config/deploy.yml` is committed and generic.
- Real values go in a destination file, `config/deploy.<destination>.yml`, which
  is gitignored. Kamal merges it over the base: `kamal deploy -d production`.
- Copy `.kamal/secrets.example` to `.kamal/secrets` (also gitignored) and wire
  it to your password manager or environment.

You will need to set, alongside the usual `RAILS_MASTER_KEY` and
`DATABASE_URL`, the three Active Record Encryption keys. Generate them with
`bin/rails db:encryption:init`.

## License

MIT
