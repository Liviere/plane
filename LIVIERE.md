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
