# Releasing MegooITAdmin

MegooITAdmin is released as one product with one version: the backend, workers, gateway, executor and frontend
always carry the same number. The bare version is in `VERSION` at the root of the repository, and every release is
tagged `vX.Y.Z`. The first release is `v0.1.0`.

A release publishes:

- the service images on GHCR, each tagged `:X.Y.Z` and `:latest` and built for amd64 and arm64;
- a GitHub release `vX.Y.Z` whose text is the release note `docs/releases/vX.Y.Z.md`.

[AGENTS.md](../AGENTS.md) carries the same rules in short form for coding agents. If you change a rule here,
change it there too.

## Branches

- Work lands on `develop`, through a work branch: `feat/…`, `fix/…` or `docs/…`, or the `megoo/<KEY>-…` branch of
  a MegooColab task. The version never changes on `develop` or on a work branch.
- `main` changes only on a release. It stays GitHub's default branch, so a plain `git clone` gets the latest
  release, not work in progress.
- Nobody commits straight to `develop` or `main`, and neither is ever force-pushed.

## Version numbers

- Fixes and small improvements give a patch release (0.1.0 → 0.1.1). Any new feature gives a minor release
  (0.1.1 → 0.2.0). A major release happens only when the owner asks, or when an admin has to act during the
  upgrade (ask first).
- Documentation changes alone need no release.

The version lives in these files, and a release sets the same version in all of them:

| File | Field |
|---|---|
| `VERSION` | The bare version, `X.Y.Z` |
| `backend/pyproject.toml`, `workers/*/pyproject.toml`, `gateway/pyproject.toml`, `executor/pyproject.toml` | `version` |
| `uv.lock` of each Python package | The package's own entry |
| `frontend/package.json` | `"version"` |
| `frontend/package-lock.json` | Both top-level `"version"` lines |

`python tools/release/versions.py check` compares every file of this table, the lock files included, with
`VERSION`.

If the product changed since its last tag, it must carry a new, higher version. The product is `backend`,
`workers`, `gateway`, `executor`, `frontend`, `caddy`, `docker-compose.yml`, `.env.example`, `Makefile` and
`VERSION`. A change anywhere else (`docs/`, `tools/`, `.github/`, `AGENTS.md`, `README.md`, `megoocolab.toml`)
needs none. `python tools/release/versions.py guard` runs this rule alone, and `plan` includes it. The release
tooling (`tools/release/versions.py` and the Release workflow) refuses anything else. The reason: servers that
follow `latest` would otherwise get a lower version, or a changed product under a version number they already run.

## The routine

A release starts only when the owner says "release". It needs `tools/release/versions.py` and the Release
workflow. If either is not in the repository yet, stop and say so.

1. **List the changes** since the last tag with `git log vX.Y.Z..develop`. The list decides the bump and fills the
   release note. If it is empty there is nothing to release, so stop and say so.
2. **Pick the bump yourself** from those changes (patch, minor or major, by the rules above), and say which one
   you picked, so the owner can object before anything is pushed.
3. **Merge:** merge `develop` into an up-to-date `main` with `--no-ff`, so the release has one merge commit that
   shows exactly what it brought in.
4. **Set the new version** in every file in the table above. One file left behind makes the versions disagree,
   and the check in step 6 fails.
5. **Write the release note** `docs/releases/vX.Y.Z.md`, for the person installing it: one opening sentence, then
   `## New`, `## Improved` and `## Fixed` (leave out an empty one; each item starts with a bold sentence), and
   `## Upgrading` last. The workflow publishes this file as the text of the GitHub release, and fails if it is not
   in git.
6. **Check:** stage the changed files, then run `make release-check`. It runs `python tools/release/versions.py
   check` (all files of the table, the lock files included, carry the same version) and
   `python tools/release/versions.py plan` (the version went up and the note is in git). Both must pass.
7. **Commit and push:** commit as `release: MegooITAdmin X.Y.Z` and push `main`. The push starts the Release
   workflow.
8. **Bring develop up to date:** merge `main` back into `develop` and push it, so `develop` carries the release
   commit and the next release starts from the right version.
9. **Watch the Release workflow** until every job is green and the release shows as Latest. Then report the
   version, what it contains and what upgrading needs. If the workflow fails, stop and report it. Never retag,
   move or delete a tag: servers and people may already have pulled it.

Steps 3 to 8 as commands (replace `X.Y.Z`; steps 4 and 5 are edits by hand):

```bash
# 3. Merge
git checkout main
git pull
git merge --no-ff develop -m "Merge branch 'develop'"

# 4. Set the new version in every file of the table
# 5. Write docs/releases/vX.Y.Z.md

# 6. Check
git add -u
git add docs/releases/vX.Y.Z.md
python tools/release/versions.py check
python tools/release/versions.py plan

# 7. Commit and push
git commit -m "release: MegooITAdmin X.Y.Z"
git push origin main

# 8. Bring develop up to date
git checkout develop
git merge main
git push origin develop
```

Step 9: `gh run list --workflow Release`, then `gh run watch <id>`, then `gh release list --limit 1`.

## The first release

`v0.1.0` has no earlier tag, so step 1 lists `git log develop` instead, and the version check has nothing to
compare with. The files already hold `0.1.0`, so step 4 changes nothing and the release commit carries only
`docs/releases/v0.1.0.md`.

## What the workflow does (.github/workflows/release.yml)

It runs on every push to `main`. Its jobs, in order:

- **plan** reads the version and fails if it did not go up since the last tag, or if the release note
  `docs/releases/vX.Y.Z.md` is not in git. A version that already has its tag, with no change to the product,
  releases nothing: `plan` prints `release=false` and the other jobs are skipped.
- **tests** reuses the CI workflow, so a release runs the same checks as every merge.
- **app** is a start-up smoke test: it brings the stack up with Docker Compose and calls `curl /api/health`.
- **images** builds every service image natively for amd64 and for arm64.
- **publish** pushes the multi-arch images to GHCR as `:X.Y.Z` and `:latest`, and creates the release with
  `gh release create vX.Y.Z` and the release note as its text. That also creates the tag.
