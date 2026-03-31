# Release Workflow

This document describes the repository release automation defined in
`.github/workflows/release-prepare.yml` and `.github/workflows/release.yml`.

## Trigger Model

The repository now uses a two-stage release flow:

1. A maintainer manually starts `Prepare Release`.
2. The workflow opens a Draft PR that synchronizes version metadata.
3. After that PR is merged into `master`, `Release` creates the Git tag and
   ensures the GitHub Release exists for the synchronized `master` commit.

This keeps the published tag aligned with the final merged commit that contains
the authoritative version metadata.

## Prepare Release

The preparation workflow is defined in `.github/workflows/release-prepare.yml`
and is triggered manually with a target version, for example `1.3.2`.

It performs these steps:

1. Normalize the requested version and derive the target tag name.
2. Refuse to continue if the target tag already exists on `origin`.
3. Synchronize repository version metadata with
   `scripts/sync_release_version.py --write`.
4. Validate the synchronized metadata with
   `scripts/sync_release_version.py --check`.
5. Open a Draft PR with the synchronized version files.

## Release

The publishing workflow is defined in `.github/workflows/release.yml`.

It runs when a push to `master` changes `VERSION`, and it also supports a
manual reconciliation mode through `workflow_dispatch`.

On the normal `push` path, the workflow:

1. Reads the release version from the checked-in `VERSION` file.
2. Verifies that the repository metadata is already synchronized.
3. Refuses to reuse a tag that points at a different commit.
4. Creates the release tag from the current `master` commit.
5. Ensures the GitHub Release exists for that tag, with generated release
   notes.

On the manual `workflow_dispatch` path, the workflow:

1. Accepts an existing release tag such as `v1.3.2`.
2. Resolves the tagged commit and validates the checked-in release metadata at
   that commit.
3. Refuses to continue if the tag does not exist or points to an unexpected
   revision.
4. Recreates the missing GitHub Release if needed, without rewriting the tag.

## Version Source of Truth

`VERSION` is the unified repository version source.

The preparation workflow writes this version into the repository metadata
before the release is cut, and the publish workflow reads it back from the
merged `master` commit. This means the tag, release notes, and checked-in
version files are derived from the same commit.

The workflow currently checks and may update these files:

- `VERSION`
- `backend/pyproject.toml`
- `frontend/package.json`
- `frontend/app.json`
- `frontend/package-lock.json`

## Recommended Release Flow

1. Choose the target version.
2. Run `Prepare Release` with a version such as `1.3.2`.
3. Review and merge the auto-created Draft PR.
4. Let `.github/workflows/release.yml` create the Git tag and GitHub Release
   from the merged `master` commit.

## Recovery Path for Missing GitHub Releases

If the release workflow succeeds in pushing the tag but fails before the
GitHub Release is created, use the manual reconciliation path:

1. Open the `Release` workflow in GitHub Actions.
2. Choose `Run workflow`.
3. Provide the existing release tag, for example `v1.3.2`.
4. Run the workflow on `master`.

Behavior:

- If the tag exists and the GitHub Release is missing, the workflow recreates
  the release.
- If the GitHub Release already exists, the workflow exits without changing
  the tag.
- If the tag does not exist, the workflow fails fast instead of creating a new
  tag from an ambiguous ref.

The release creation step uses limited retry logic to reduce transient GitHub
API failures before surfacing an error.

## Local or CI Validation

Use the helper script below to verify metadata consistency against a target
version:

```bash
python3 scripts/sync_release_version.py --version 1.0.0 --check
```

Use this command to write the synchronized metadata locally when needed:

```bash
python3 scripts/sync_release_version.py --version 1.0.0 --write
```

## Release Preparation Pull Request Behavior

If synchronized metadata differs from the checked-in repository files, the
preparation workflow automatically opens a Draft pull request to persist those
changes.

Current behavior in `.github/workflows/release-prepare.yml`:

- PR branch pattern: `release/version-<version>`
- Commit title style: `chore(release): sync version metadata for <version> (#586)`
- Base branch: `master`

Review the workflow files directly if any of these conventions change.
