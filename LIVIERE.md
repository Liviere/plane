# Liviere/plane fork

A fork of Plane Community Edition with our own changes; it runs `plane.liviere.studio`.

## Branches

- `master`, `preview` – exact mirrors of [makeplane/plane](https://github.com/makeplane/plane). Never commit
  to them, only sync them with upstream.
- `liviere` – our changes on top of an official release (started from tag `v1.4.2`). New features go to
  `feat/*` branches and are merged into `liviere` via PR (note: in a fork GitHub suggests `makeplane/plane`
  as the PR target – change it).

## Releases and images

A `v<official version>-liviere.<n>` tag (e.g. `v1.4.2-liviere.1`) runs `.github/workflows/liviere-images.yml`,
which builds 6 images `ghcr.io/liviere/plane-{frontend,space,admin,live,backend,proxy}:<tag>`.
On the server: `PLANE_IMAGE_REPO=ghcr.io/liviere` and `APP_RELEASE=<tag>` in `plane.env`.

## Updating to a new official release

```sh
git fetch upstream --tags
git switch liviere && git merge v1.4.3   # an official tag, not preview
git tag v1.4.3-liviere.0 && git push origin liviere v1.4.3-liviere.0
```

Never merge `preview` – it carries database migrations that releases do not have yet.

## Rules for our changes

- **Database:** our own models live in a separate Django app (`apps/api/plane/liviere/`) with its own
  migrations. Do not add files to `apps/api/plane/db/migrations/` (numbering clashes with upstream). Instead of
  altering official tables, add separate tables linked 1:1 or by a foreign key.
- **Frontend:** new code in separate files, hook points in the `ce/` layers (e.g. `apps/web/ce/`); change as
  few lines as possible in official files.
- Until the first migration of our own, going back to the official images is a change of two variables in
  `plane.env`; after that only by restoring a database backup.
- **Language:** code comments, documentation and commit messages are in English.

## Project pages API (`/api/v1/.../projects/{id}/pages/`)

Our code is in `apps/api/plane/liviere/api/` (routes included from `apps/api/plane/api/urls/__init__.py`),
tests in `apps/api/plane/tests/contract/api/test_pages.py`, a compatibility check against `plane-sdk==0.3.1`
in `apps/api/plane/liviere/scripts/sdk_pages_smoke.py`. The contract follows the SDK: list, retrieve, create,
`PUT`/`PATCH` (both partial), `POST`/`DELETE .../archive/`, `DELETE` (archived pages only).
Permissions are the same as in the UI (`ProjectPagePermission`).

**Limitation – content of pages opened in the editor.** The editor works on the Yjs state
(`description_binary`), which the `live` server stores the first time a page is opened. Replacing
`description_html` and clearing the binary only works until someone opens the page. After that an open
editor overwrites the change within ~10 s, and a browser with a cached copy of the page (y-indexeddb) merges
the old content with the new one – the content gets duplicated and saved to the database (verified on a
local stack). So the API refuses content changes (409, nothing written) once a page has a
`description_binary`; the name and other fields can always be changed. Creating pages with content has no
such limit.

This cannot be solved in the backend alone: force-closing a document via Redis (`hocuspocus:admin`) first
stores the in-memory state, and after the disconnect the frontend writes the old content back itself;
`PUBSUB NUMSUB hocuspocus:<id>` does not tell whether a page is open (`@hocuspocus/extension-redis` 2.15.2
never unsubscribes the channel once the document is unloaded). A full fix needs a change in `apps/live`:
replacing the content as a regular Yjs edit on the existing document (a new command on `hocuspocus:admin` or
an endpoint protected by `LIVE_SERVER_SECRET_KEY`).
