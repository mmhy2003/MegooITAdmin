# MITA-2 implementation plan: bootstrap the repository

## Goal

Land the directory layout, `AGENTS.md`, `CLAUDE.md`, `VERSION` and `docs/releasing.md` on `develop` (through the MegooColab PR from `megoo/MITA-2-…`), so a coding agent can follow the branch, commit, check and release flow from `AGENTS.md` alone.

## Architecture

The task adds documents and empty placeholder files. There is no code. `AGENTS.md` is the single source of truth, `CLAUDE.md` imports it with one line, and `docs/releasing.md` is the long form of the release rules for people. It must agree with `AGENTS.md` on the version-file table, the bump rules and the nine routine steps. Each empty directory of the layout keeps an empty `.gitkeep`.

## Facts about the repo (checked at `d40d126`)

- One tracked file: `README.md` (`# MegooITAdmin`). It stays unchanged.
- Local and remote `develop` and `main` both sit at `d40d126`, and `main` is the default branch. No branch is created.
- Work happens on the current branch `megoo/MITA-2-p0-01-bootstrap-repo-branches-layout-age`. MegooColab opens the PR into `develop`.
- No test framework, Compose file, Makefile or CI exists. The checks below are shell checks on the files. No check needs a container, so there is **no `megoocolab.toml` step**.
- Under the new Checks rule, all four `AGENTS.md` checks (backend, frontend, security suites, release tools) are skipped in this task because their parts don't exist. The implementer says so in the finish report.

## File map

| Path | Responsibility | Step |
|---|---|---|
| `frontend/.gitkeep`, `backend/.gitkeep`, `workers/collector/.gitkeep`, `workers/agents/.gitkeep`, `workers/scheduler/.gitkeep`, `workers/indexer/.gitkeep`, `gateway/.gitkeep`, `executor/.gitkeep`, `caddy/.gitkeep`, `tools/release/.gitkeep`, `docs/releases/.gitkeep` | Empty (0 bytes). They keep the layout in git until a later task adds real files | 1 |
| `VERSION` | Exactly `0.1.0` plus a newline | 1 |
| `AGENTS.md` | Agent rules, eight sections (Appendix A) | 2 |
| `CLAUDE.md` | Exactly `@AGENTS.md` plus a newline | 2 |
| `docs/releasing.md` | Release procedure for people (Appendix B) | 3 |

After step 3, `git ls-files` lists exactly 16 paths.

**Escaping note:** the design shows `&lt;KEY&gt;`, `&lt;branch&gt;`, `&lt;changed files&gt;` and `&lt;id&gt;` as HTML entities. These are display escapes. The files must contain the real characters `<KEY>`, `<branch>`, `<changed files>` and `<id>`. The appendices below already use real characters.

## Steps

### 1. Add the directory layout and VERSION

**Test first.** From the repository root, run:

```bash
for d in frontend backend workers/collector workers/agents workers/scheduler workers/indexer gateway executor caddy tools/release docs/releases; do
  { test -f "$d/.gitkeep" && test ! -s "$d/.gitkeep"; } || echo "missing $d/.gitkeep"
done
printf '0.1.0\n' | cmp - VERSION && echo "VERSION ok"
```

Expected failure: 11 `missing …/.gitkeep` lines and `cmp: VERSION: No such file or directory`.

**Implement.**

```bash
for d in frontend backend workers/collector workers/agents workers/scheduler workers/indexer gateway executor caddy tools/release docs/releases; do
  mkdir -p "$d" && : > "$d/.gitkeep"
done
printf '0.1.0\n' > VERSION
```

**Run again.** No `missing` line, and `VERSION ok`. Also `git status --porcelain` shows 12 untracked paths (11 `.gitkeep` and `VERSION`) and no change to `README.md`.

**Commit:** `git add` the 12 files, then commit with:

```
chore(repo): the repository has its directory layout and version 0.1.0

The PRD fixes one layout for the services, workers, release tools and release notes. Git doesn't track empty directories, so each one holds an empty .gitkeep that the task adding its first real file deletes. VERSION starts at 0.1.0, the first release.
```

### 2. Add AGENTS.md and CLAUDE.md

**Test first.** From the repository root, run:

```bash
grep -c '^## ' AGENTS.md
grep '^## ' AGENTS.md | sed 's/^## //' | paste -sd'|' -
for s in megooitadmin-dev megooitadmin-e2e megooitadmin_migrate 'A check applies once its part is in the repository' 'megoo/<KEY>-' 'release: MegooITAdmin X.Y.Z' '[docs/releasing.md](docs/releasing.md)'; do grep -qF -- "$s" AGENTS.md || echo "missing: $s"; done
grep -cE '&lt;|&gt;' AGENTS.md
printf '@AGENTS.md\n' | cmp - CLAUDE.md && echo "CLAUDE.md ok"
```

Expected failure: `grep: AGENTS.md: No such file or directory` and `cmp: CLAUDE.md: No such file or directory`.

**Implement.**

- Write `AGENTS.md` with the exact text of Appendix A. It is the design's "AGENTS.md (full text)" with the HTML entities turned into real `<` and `>`. Keep the line wrapping, the fenced block of the three choices, and the table as they are. End the file with one newline.
- `printf '@AGENTS.md\n' > CLAUDE.md`

**Run again.** Expected output:

```
8
Branches|Finishing work|How to work|Commits|Checks|Migrations|Safety|Versioning and releases
0
CLAUDE.md ok
```

No `missing:` line (the `0` is the entity count).

**Commit:** `git add AGENTS.md CLAUDE.md`, then commit with:

```
docs(agents): AGENTS.md tells coding agents how to branch, check and release

Any coding agent must be able to follow the branch, commit, check and release flow without asking. AGENTS.md is the single source of truth, and CLAUDE.md only imports it so the two cannot drift. Checks apply once their part exists, MegooColab task branches are covered, and the Compose projects and scratch database are named now so later tasks use those names.
```

### 3. Add docs/releasing.md

**Test first.** From the repository root, run:

```bash
grep -E '^#{1,2} ' docs/releasing.md
diff <(grep '^| ' AGENTS.md) <(grep '^| ' docs/releasing.md) && echo "table ok"
diff <(grep -oE '^[1-9]\. \*\*[^*]+\*\*' AGENTS.md) <(grep -oE '^[1-9]\. \*\*[^*]+\*\*' docs/releasing.md) && echo "steps ok"
for s in 'Fixes and small improvements give a patch release (0.1.0 → 0.1.1)' 'Any new feature gives a minor release' 'A major release happens only when the owner asks' 'Documentation changes alone need no release' 'it must carry a new, higher version'; do grep -qF -- "$s" docs/releasing.md || echo "missing: $s"; done
```

Expected failure: `grep: docs/releasing.md: No such file or directory`, then the two `diff` commands print the whole table and the nine step titles as missing.

**Implement.** Write `docs/releasing.md` with the exact text of Appendix B. End the file with one newline. Don't add a second table: the table check compares every `| ` line.

**Run again.** Expected output:

```
# Releasing MegooITAdmin
## Branches
## Version numbers
## The routine
## The first release
## What the workflow does (.github/workflows/release.yml)
table ok
steps ok
```

No `missing:` line. Then run the final verification below. It must pass in full.

**Commit:** `git add docs/releasing.md`, then commit with:

```
docs(releasing): docs/releasing.md describes the release procedure for people

AGENTS.md carries the release rules in short form for agents. People need the reasons behind each step, what the Release workflow does, and how the first release differs. The file table, the bump rules and the nine steps match AGENTS.md word for word.
```

## Final verification

From the repository root, on the work branch after step 3:

```bash
git ls-files | sort
# Expected, exactly these 16 lines:
# AGENTS.md
# CLAUDE.md
# README.md
# VERSION
# backend/.gitkeep
# caddy/.gitkeep
# docs/releases/.gitkeep
# docs/releasing.md
# executor/.gitkeep
# frontend/.gitkeep
# gateway/.gitkeep
# tools/release/.gitkeep
# workers/agents/.gitkeep
# workers/collector/.gitkeep
# workers/indexer/.gitkeep
# workers/scheduler/.gitkeep
git ls-files | wc -l                                   # 16
printf '0.1.0\n' | cmp - VERSION && echo VERSION ok
printf '@AGENTS.md\n' | cmp - CLAUDE.md && echo CLAUDE ok
git grep -c '^## ' AGENTS.md                           # AGENTS.md:8
git diff develop --stat                                # 15 files changed, insertions only
git diff develop --diff-filter=MDR --name-only         # empty: nothing changed or removed, README.md untouched
find . -name .gitkeep -not -path './.git/*' -size +0c  # empty: every .gitkeep is 0 bytes
git log --oneline develop..HEAD                        # the three commits of steps 1 to 3
```

Read `AGENTS.md` alone and answer: which branch work starts from (`develop`, up to date) and how it is named (`feat/…`, `fix/…`, `docs/…`, or MegooColab's `megoo/<KEY>-…`), what a commit subject looks like, what "1", "push" and "release" mean, and what to do when a check's tool is missing (skip it, name it, never report it as passed). Report that the four `AGENTS.md` checks were skipped because their parts don't exist yet.

## Appendix A: `AGENTS.md` (exact text)

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

## Appendix B: `docs/releasing.md` (exact text)

~~~~markdown
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

If the product changed since its last tag, it must carry a new, higher version. The release tooling
(`tools/release/versions.py` and the Release workflow) refuses anything else. The reason: servers that follow
`latest` would otherwise get a lower version, or a changed product under a version number they already run.

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
6. **Check:** stage the changed files, then run `python tools/release/versions.py check` (all files carry the same
   version) and `python tools/release/versions.py plan` (the version went up and the note exists). Both must pass.
   The tool doesn't read the lock files for you, so check them by hand: `git diff --cached` shows the new version
   in every `uv.lock` and in `frontend/package-lock.json`.
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
git diff --cached

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
  `docs/releases/vX.Y.Z.md` is not in git.
- **tests** reuses the CI workflow, so a release runs the same checks as every merge.
- **app** is a start-up smoke test: it brings the stack up with Docker Compose and calls `curl /api/health`.
- **images** builds every service image natively for amd64 and for arm64.
- **publish** pushes the multi-arch images to GHCR as `:X.Y.Z` and `:latest`, and creates the release with
  `gh release create vX.Y.Z` and the release note as its text. That also creates the tag.
~~~~
