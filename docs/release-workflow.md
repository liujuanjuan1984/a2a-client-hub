# Release Workflow

This document describes the repository release automation defined in
`.github/workflows/release.yml`.

## Trigger

The workflow listens for pushed Git tags that match the `v*` pattern.

Example:

- `v1.0.0`

When such a tag is pushed, GitHub Actions creates a GitHub Release
automatically.

## What the Workflow Does

1. Resolve the release version from the pushed tag.
2. Synchronize repository version metadata with
   `scripts/sync_release_version.py --write`.
3. Validate the synchronized metadata with
   `scripts/sync_release_version.py --check`.
4. Create a GitHub Release with generated release notes.
5. Open a follow-up pull request if versioned repository files changed during
   metadata synchronization.

## Version Source of Truth

`VERSION` is the unified repository version source.

During a tag-driven release, the workflow treats the pushed tag as the release
identity and synchronizes versioned repository metadata to that version. This
means you do not need to manually bump every metadata file before cutting a
release tag.

The workflow currently checks and may update these files:

- `VERSION`
- `backend/pyproject.toml`
- `frontend/package.json`
- `frontend/app.json`
- `frontend/package-lock.json`

## Recommended Release Flow

1. Choose the target version.
2. Push a matching Git tag such as `v1.0.0`.
3. Let `.github/workflows/release.yml` create the GitHub Release.
4. Review the auto-created version sync pull request if repository metadata was
   updated during the release.

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

## Follow-Up Pull Request Behavior

If synchronized metadata differs from the checked-in repository files, the
workflow automatically opens a follow-up pull request to persist those changes.

Current behavior in `.github/workflows/release.yml`:

- PR branch pattern: `release/version-<version>`
- Commit title style: `chore(release): sync version metadata for <version> (#586)`
- Base branch: `master`

Review the workflow file directly if any of these conventions change.
