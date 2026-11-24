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

- **Backend** (`backend/`): `megoocolab-runner services run test -- uv run pytest`, then the container start-up
  tests: `megoocolab-runner services run image -- uv run pytest -m docker`.
- **Frontend** (`frontend/`): `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`, then the image
  check: `megoocolab-runner services run web -- npm run test:image`.
- **Stack** (`backend/`): `megoocolab-runner services run stack -- uv run pytest -m stack`. It starts the whole
  Compose stack, built from this checkout through `docker-compose.build.yml`, and checks it through Caddy. `make test` runs the backend, frontend and stack checks in one go.
- **Security suites**: `make test-security`. It runs the audit-coverage, audit-tamper, database-privilege,
  auth-coverage, auth-events, permission-coverage, access-events, host-key-pinning and server-setup suites. The secret-leak and approval-bypass
  suites join it with Phases 3 and 4.
- **Release tools** (repository root): `uv run --project backend pytest tools/release`, then
  `python tools/release/versions.py check`. `make release-check` runs `check` and `plan` and belongs to a release
  (step 6 below), because `plan` passes only there.

A check applies once its part is in the repository. While a part is missing (a directory that holds only
`.gitkeep`, a Makefile target that doesn't exist yet or says its part is not in the repository yet), skip its
check and say which checks you skipped and why. Never report a skipped check as passed.

CI (`.github/workflows/ci.yml`) runs all of these checks on every pull request into `develop` and on every push to
it, and the Release workflow reuses it. It installs the `megoocolab-runner` version set in `MEGOO_RUNNER_VERSION` in
that file. CI does not replace the checks above: run them before you push.

## Migrations

- Alembic revisions are numbered, not hashed: `0001_initial.py`, `0002_add_users.py`.
- Generate and try migrations only on the scratch database `megooitadmin_migrate`, never on the dev database and
  never inside a running container. The `migrate` service set starts that database, empty, in this worktree's own
  container, and removes it when the command ends. Run these from `backend/`.
- Create each migration with the next number: `make migration name=add_users`. It runs, from `backend/`:
  `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic revision --autogenerate --rev-id 0002 -m "add users"'`
- Before committing, check that the migration goes down and up again:
  `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- A migration that creates a table grants `megooitadmin_api`, the role the backend serves as, what the table needs
  (nothing more), and adds the table to `API_GRANTS` in `backend/tests/security/test_db_privileges.py`. A table
  without a grant stays closed to the backend.

## Safety

- Docker: start containers for checks only with `megoocolab-runner services run`. It gives this worktree its own
  `megoo-…` containers and removes them when the command ends. Apart from those, use only the `megooitadmin-dev`
  and `megooitadmin-e2e` Compose projects. Start them with `make up STACK=dev` and `make up STACK=e2e`, and pass
  the same `STACK=` to `down`, `logs`, `migrate` and `shell-backend`. Never run one of these targets without
  `STACK=`: it then acts on the owner's real instance. Never stop, remove or change any other container. A
  `megooitadmin` project and its `megooitadmin-*` containers are the owner's real instance.
- Never run `make upgrade`: it pulls new images and restarts the owner's real instance. It refuses `STACK=`; a dev
  or e2e stack takes `make up STACK=…` again.
- Never read files that hold credentials or secrets (`.env` files, tokens, keys).
- Never connect to a managed server. Use the fake-server fixture (containers with sshd) instead.
- The test set starts its own fake server. `make up STACK=dev` and `make up STACK=e2e` start one too and authorize
  that stack's key on it: register it as address `fake-server`, port 22. `make fake-server-swap STACK=dev` gives
  it new host keys. Never run `fake-server-swap` without `STACK=`.
- The fake server is prepared by `backend/app/ssh/megoo-setup.sh`, like a real one. It has `megoo` plus the wrong
  accounts `megoo-docker`, `megoo-root`, `megoo-nologs`, `megoo-nosudo` and `megoo-wide`.
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
6. **Check:** `git add` the changed files, then `make release-check`. It runs
   `python tools/release/versions.py check` (every file in the table above, the lock files included, carries the
   same version) and `python tools/release/versions.py plan` (the version went up and the release note is in
   git). Both must pass.
7. **Commit and push:** `git commit -m "release: MegooITAdmin X.Y.Z"`, then `git push origin main`.
8. **Bring develop up to date:** `git checkout develop && git merge main && git push origin develop`.
9. **Watch the Release workflow** (`gh run list --workflow Release`, then `gh run watch <id>`) until every job is
   green and the release shows as Latest (`gh release list --limit 1`). Then report the version, what it contains
   and what upgrading needs. If the workflow fails, stop and report it. Never retag, move or delete a tag.

For `v0.1.0` there is no earlier tag and the files already hold `0.1.0`: list `git log develop` in step 1, and
step 4 changes nothing.

If `tools/release/versions.py` or the Release workflow is not in the repository yet, stop and say so.
