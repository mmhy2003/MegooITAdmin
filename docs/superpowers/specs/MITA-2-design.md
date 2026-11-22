# MITA-2 design: bootstrap the repository (layout, AGENTS.md, CLAUDE.md, VERSION, docs/releasing.md)

## Goal

After this task, `develop` holds the directory layout, the agent instructions, `VERSION` and the release procedure. A coding agent that reads only `AGENTS.md` knows how to branch, commit, check, finish and release in this repository.

## What the repository looks like today

- One commit (`d40d126 Initial commit`) and one file: `README.md` with the line `# MegooITAdmin`.
- `develop` and `main` already exist on GitHub, both at that commit, and `main` is the default branch. **No branch has to be created.** The task only has to land its files on `develop`.

## Decisions

Answers from the owner:

1. **`AGENTS.md` is written in full now, with one "applies once it exists" rule.** All eight sections get their final text from PRD §3.9–3.10. A rule in Checks says a check applies once its part is in the repository, and a skipped check is named, never reported as passed. Rejected: the PRD text with no caveat (agents would hit failing commands until P0.12), and a file that grows task by task (every Phase 0 task would have to remember to edit it).
2. **A short note covers MegooColab task branches.** A `megoo/<KEY>-…` branch is the work branch, and MegooColab's workflow finishes the work with a PR into `develop`, so the three-option menu is not offered there. Rejected: keeping only the PRD text.
3. **Names are fixed now:** dev Compose project `megooitadmin-dev`, end-to-end Compose project `megooitadmin-e2e`, scratch migration database `megooitadmin_migrate`. P0.02 (MITA-5) and P0.04 (MITA-4) must use them. Rejected: generic wording filled in later.

Decisions I made (say so if you want them changed):

4. **Eight sections, as the PRD lists them.** MegooColab's own `AGENTS.md` has six (its finish menu sits under Branches, migrations under Checks). The PRD and the task name eight, so the structure follows the PRD and the wording follows MegooColab's file where the rule is the same.
5. **Empty directories are kept with a `.gitkeep` file**, because git does not track empty directories. The task that adds the first real file to a directory deletes its `.gitkeep`. Rejected: a README stub per directory, which later tasks would have to rewrite or remove anyway.
6. **The version guard is described as a rule, not as a command.** The routine runs only `versions.py check` and `plan`, as in PRD §3.10 step 6. MegooColab's tool has no `guard` subcommand (`plan` calls it internally), and MITA-3 has not built MITA's tool yet, so this wording stays true either way.
7. **One addition is left for MITA-5:** the exact command lines that create and point at `megooitadmin_migrate`. The host, port and credentials of the dev database do not exist yet. The rules and the database name are final now.
8. **`README.md` is not changed.** There is no set-up to document yet.

## Architecture

Sixteen tracked files after the task: the existing `README.md`, four documents and eleven placeholders.

```text
AGENTS.md
CLAUDE.md                      exactly one line: @AGENTS.md
VERSION                        exactly one line: 0.1.0
README.md                      unchanged
docs/releasing.md
docs/releases/.gitkeep
frontend/.gitkeep
backend/.gitkeep
workers/collector/.gitkeep
workers/agents/.gitkeep
workers/scheduler/.gitkeep
workers/indexer/.gitkeep
gateway/.gitkeep
executor/.gitkeep
caddy/.gitkeep
tools/release/.gitkeep
```

Each `.gitkeep` is empty. `CLAUDE.md` and `VERSION` end with a newline and hold nothing else.

`AGENTS.md` is the single source of truth. `CLAUDE.md` imports it, so the two cannot drift. `docs/releasing.md` is the long form of the release rules for people, and `AGENTS.md` carries the same rules in short form. The two must agree on the file table, the bump rules and the nine steps.

## Data and interfaces

### `AGENTS.md` (full text)

~~~~markdown
# Working in MegooITAdmin

Rules for coding agents working in this repository. The owner gives short instructions ("push", "release", "1");
this file says what each one means here. [docs/releasing.md](docs/releasing.md) is the full reference for releases.

## Branches

- `develop` is where work lands. `main` changes only on a release, and stays GitHub's default branch.
- Start every piece of work on its own branch off an up-to-date `develop`: `feat/…`, `fix/…` or `docs/…`.
- Never commit straight to `develop` or `main`, and never force-push either of them.
- In a MegooColab task, the branch MegooColab created (`megoo/<KEY>-…`) is the work branch. Don't create another.

## Finishing work

- When the work is done and its checks pass, offer exactly these choices, then wait for the answer:

  ```
  1. Merge back to develop locally
  2. Push and create a Pull Request
  3. Keep the branch as-is (I'll handle it later)
  ```

  - "1" means `git merge --no-ff <branch>` into `develop`, run the checks again on the result, then delete the
    branch. It does not push.
  - "2" means push the branch and open a pull request into `develop`.
  - "3" means leave the branch as it is.
- **Push only when the owner says "push"**, and **release only when the owner says "release"**. Neither is implied
  by a merge, or by an earlier "push" or "release" for other work.
- In a MegooColab task, MegooColab's workflow finishes the work with a pull request into `develop`. Don't offer
  the choices above.

## How to work

- A change to what people see (a page, a dialog, a layout) gets a mockup first. Build it only after the owner
  approves the mockup.
- Write the test first and watch it fail, then make it pass. A bug fix starts with a test that reproduces it.

## Commits

- Subject: `type(area): what changed`, as a plain sentence, for example
  `feat(inventory): an admin can register a server`. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
- Body: why the change was needed, in plain sentences.
- Merges keep git's message: `Merge branch '<branch>' into develop`.
- A release commit is `release: MegooITAdmin X.Y.Z`.

## Checks

Run these before any merge:

- **Backend** (`backend/`): `uv run pytest`.
- **Frontend** (`frontend/`): `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`.
- **Security suites**: `make test-security`. It runs the secret-leak, approval-bypass and audit-coverage suites
  against the fake-server fixture.
- **Release tools**: `make release-check`. It runs `python tools/release/versions.py check` and `plan`.

A check applies once its part is in the repository. While a part is missing (a directory that holds only
`.gitkeep`, a Makefile target that doesn't exist yet), skip its check and say which checks you skipped and why.
Never report a skipped check as passed.

## Migrations

- Alembic revisions are numbered, not hashed: `0001_initial.py`, `0002_add_users.py`. Create each one with the
  next number: `alembic revision --autogenerate --rev-id 0002 -m "add users"`.
- Generate and try migrations only on the scratch database `megooitadmin_migrate`, never on the dev database and
  never inside a running container.
- Before committing, check on the scratch database that the migration goes down and up again:
  `uv run alembic downgrade -1`, then `uv run alembic upgrade head`.

## Safety

- Docker: use only the `megooitadmin-dev` and `megooitadmin-e2e` Compose projects. Never stop, remove or change
  any other container. A `megooitadmin` project and its `megooitadmin-*` containers are the owner's real instance.
- Never read files that hold credentials or secrets (`.env` files, tokens, keys).
- Never connect to a managed server. Use the fake-server fixture (containers with sshd) instead.
- You have no access to production. Don't try to reach it.

## Versioning and releases

MegooITAdmin is released as one product: the backend, workers, gateway, executor and frontend always carry the
same version. Tags are `vX.Y.Z`, and the first release is `v0.1.0`.

The version lives in:

| File | Field |
|---|---|
| `VERSION` | The bare version, `X.Y.Z` |
| `backend/pyproject.toml`, `workers/*/pyproject.toml`, `gateway/pyproject.toml`, `executor/pyproject.toml` | `version` |
| `uv.lock` of each Python package | The package's own entry |
| `frontend/package.json` | `"version"` |
| `frontend/package-lock.json` | Both top-level `"version"` lines |

- The version never changes on `develop` or on a work branch: only in the release commit, on `main`.
- Fixes and small improvements give a patch release (0.1.0 → 0.1.1). Any new feature gives a minor release
  (0.1.1 → 0.2.0). A major release happens only when the owner asks, or when an admin has to act during the
  upgrade (ask first).
- Documentation changes alone need no release.
- If the product changed since its last tag, it must carry a new, higher version. The release tooling refuses
  anything else: a lower version would move servers that follow `latest` backwards.

When the owner says "release":

1. **List the changes** since the last tag: `git log vX.Y.Z..develop`. If there are none, stop and say there is
   nothing to release.
2. **Pick the bump yourself** from those changes, and say which one you picked.
3. **Merge:** `git checkout main && git pull && git merge --no-ff develop -m "Merge branch 'develop'"`.
4. **Set the new version** in every file in the table above.
5. **Write the release note** `docs/releases/vX.Y.Z.md`, for the person installing it: one opening sentence, then
   `## New`, `## Improved` and `## Fixed` (leave out an empty one; each item starts with a bold sentence), and
   `## Upgrading` last.
6. **Check:** `git add` the changed files, then `python tools/release/versions.py check` and
   `python tools/release/versions.py plan`. Both must pass. Check the lock files by hand:
   `git diff --cached` shows the new version in every `uv.lock` and in `frontend/package-lock.json`.
7. **Commit and push:** `git commit -m "release: MegooITAdmin X.Y.Z"`, then `git push origin main`.
8. **Bring develop up to date:** `git checkout develop && git merge main && git push origin develop`.
9. **Watch the Release workflow** (`gh run list --workflow Release`, then `gh run watch <id>`) until every job is
   green and the release shows as Latest (`gh release list --limit 1`). Then report the version, what it contains
   and what upgrading needs. If the workflow fails, stop and report it. Never retag, move or delete a tag.

For `v0.1.0` there is no earlier tag and the files already hold `0.1.0`: list `git log develop` in step 1, and
step 4 changes nothing.

If `tools/release/versions.py` or the Release workflow is not in the repository yet, stop and say so.
~~~~

### `docs/releasing.md` (outline)

Written for people, with the same rules as `AGENTS.md` in longer form. It mirrors MegooColab's `docs/releasing.md` without the runner product.

| Heading | Content |
|---|---|
| `# Releasing MegooITAdmin` | One product with one version. The version file (`VERSION`), the tag (`vX.Y.Z`) and what a release publishes: service images on GHCR as `:X.Y.Z` and `:latest` for amd64 and arm64, and a GitHub release with the release note |
| `## Branches` | Work lands on `develop` and the version never changes there. `main` changes only on a release and stays the default branch, so a plain `git clone` gets the latest release |
| `## Version numbers` | The bump rules (patch, minor, major). The table of files that hold the version. The guard rule: a product changed since its last tag needs a new, higher version. Documentation alone needs no release |
| `## The routine` | The nine steps of `AGENTS.md`, each with its reason, and one bash block for steps 3 to 8 |
| `## The first release` | `v0.1.0`: no earlier tag, the files already hold `0.1.0`, so the release commit carries only `docs/releases/v0.1.0.md` |
| `## What the workflow does (.github/workflows/release.yml)` | On every push to `main`: `plan` (fails if the version did not go up or the release note is missing from git), `tests` (reuses CI), `app` (start-up smoke test: compose up, `curl /api/health`), `images` (native amd64 and arm64 builds), `publish` (multi-arch images, `gh release create vX.Y.Z` with the note) |

## Error handling and edge cases

- **Nothing to check in this task.** No backend, frontend, Makefile or release tool exists yet, so the implementer skips all four checks and says so. That is the new rule applied for the first time.
- **`main` stays at the initial commit** until the first release (P0.12) merges `develop` into it. Until then GitHub's default view shows only `README.md`. This is the intended meaning of "`main` holds releases only".
- **`VERSION` is `0.1.0` before any release.** There is no tag yet, so the guard has nothing to compare with, and the first release needs no bump. `AGENTS.md` and `docs/releasing.md` both say this.
- **A `.gitkeep` left behind** after a directory gets real files is harmless, but the task that fills the directory should delete it.
- **"release" before the tooling exists.** `AGENTS.md` tells the agent to stop and say so.
- **This task itself runs on a `megoo/MITA-2-…` branch** and reaches `develop` through MegooColab's PR, which matches the note added to Branches and Finishing work.

## Testing

There is no code, so the checks are on the files. They can be run by hand after the build:

- `git ls-files` lists exactly the sixteen paths in the Architecture section.
- `VERSION` holds exactly `0.1.0` and `CLAUDE.md` holds exactly `@AGENTS.md`, each on one line.
- `git grep -c '^## ' AGENTS.md` gives 8, and the headings are, in order: Branches, Finishing work, How to work, Commits, Checks, Migrations, Safety, Versioning and releases.
- `AGENTS.md` contains the three fixed names (`megooitadmin-dev`, `megooitadmin-e2e`, `megooitadmin_migrate`) and the "applies once its part is in the repository" rule.
- `AGENTS.md` and `docs/releasing.md` agree: the same version-file table, the same bump rules, the same nine steps.
- `git diff develop --stat` shows only added files and no change to `README.md`.
- Read-through for the "done when": from `AGENTS.md` alone, a reader can answer which branch to start from, how to name it, what a commit subject looks like, what "1", "push" and "release" each mean, and what to do when a check's tool is missing.

## Out of scope

- Creating branches or changing the GitHub default branch (already in place), and branch protection rules on GitHub.
- `Makefile`, `docker-compose.yml`, `caddy/Caddyfile` (MITA-4), the backend and frontend skeletons (MITA-5, MITA-6), `tools/release/versions.py` (MITA-3), the fake-server fixture (MITA-11), `ci.yml` (MITA-12), `release.yml` and the `v0.1.0` release with its note (MITA-13).
- The exact scratch-database command lines under Migrations (MITA-5 adds them).
- `.gitignore`, `.gitattributes`, licence and any change to `README.md`.
