# MITA-12 design: CI workflow (`.github/workflows/ci.yml`)

## Goal

Every pull request into `develop`, and every push to `develop`, runs all the checks that `AGENTS.md` asks for before a merge, on GitHub, and shows one result per check. The Release workflow (MITA-13) can call the same workflow, so a release runs the same checks as a merge.

## What the repository looks like today

- There is no `.github/` directory. Every check is run by hand.
- Every check that needs a container runs through `megoocolab-runner services run <set> -- <command>`. `megoocolab.toml` declares five sets: `test`, `migrate`, `image`, `web` and `stack`.
- The tests depend on what the runner sets: `TEST_DATABASE_URL`, `TEST_DATABASE_OWNER_URL`, `SSH_PORT`, and `MEGOO_SERVICES_PROJECT`. `backend/tests/fake_server.py` finds the fake server with `docker ps` and the Compose project label, then calls `docker exec`. So GitHub's own `services:` containers cannot serve these tests.
- `make test-security` stops when `megoocolab-runner` is not on `PATH`.
- The backend has no linter. The frontend has ESLint (`npm run lint` runs `eslint` on the whole project).
- `uv run pytest` already includes `tests/security` (only the `docker` and `stack` markers are left out by default).

## Decisions

1. **CI runs the four checks of the task and the three slower ones.** The owner chose this. The three slower ones are the backend image start-up tests, the frontend image check and the whole stack through Caddy. Rejected: only the four listed checks, and adding the slower ones in a follow-up task.
2. **CI installs the published `megoocolab-runner`, pinned to one version, and runs the commands of `AGENTS.md` unchanged.** The owner chose this. `megoocolab.toml` stays the only description of the services. When a set later gains Valkey or Meilisearch, CI gets them with no change to `ci.yml`. Rejected: a script in this repository that copies what `services run` does (a second implementation to keep in step), and plain `docker compose` steps in `ci.yml` (the ports, names and URLs would be copied, and `make test-security` would need a Makefile change).
3. **One job per check, seven jobs, all in parallel.** A failed check is visible by name on the pull request, and the slow jobs do not hold back the fast ones. No job depends on another.
4. **`security` is its own job and runs `make test-security`,** as the task says, although `uv run pytest` in the `backend` job runs the same files. The price is about a minute of repeated work. The gain is a named security result, and a job that is already in place when the secret-leak and approval-bypass suites arrive.
5. **No path filters.** A documentation-only pull request runs every job too. A filtered job never reports, and a required check that never reports blocks the merge.
6. **The runner version lives in one place:** the workflow-level variable `MEGOO_RUNNER_VERSION` in `ci.yml`. Each job that needs the runner installs it with the install script the MegooColab project confirmed (MC-Q11). The script checks the download's SHA-256 against the release's `checksums.txt`, and needs no token.
7. **The workflow's text is tested,** in `backend/tests/test_workflows.py`. A workflow only runs on GitHub, so the test reads the YAML and checks the triggers, the permissions and the command of each job. MegooArti does the same (MA-10). `pyyaml` joins the backend's `dev` dependency group: it is already in `uv.lock` through `uvicorn[standard]`, but a test must not lean on a dependency of a dependency.
8. **No Docker layer cache and no lint for the backend.** Neither is needed for a green run. A cache can be added when the run time hurts.

## Architecture

One new workflow file, one new test file, and small edits to two existing files.

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | New: the workflow below |
| `backend/tests/test_workflows.py` | New: checks of the workflow's text |
| `backend/pyproject.toml`, `backend/uv.lock` | `pyyaml` in the `dev` group |
| `AGENTS.md` | "Checks" gets a short paragraph about CI (below) |

`Makefile`, `megoocolab.toml`, the Compose files and `docs/releasing.md` do not change. `docs/releasing.md` already says that the release's `tests` job reuses the CI workflow.

### The workflow

```yaml
name: CI

on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]
  workflow_call:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

env:
  MEGOO_RUNNER_VERSION: "X.Y.Z"   # the pinned megoocolab-runner
  UV_LOCKED: "1"                  # uv fails when uv.lock is out of date
```

- **Triggers.** Pushes to `develop`, pull requests into `develop`, and `workflow_call` with no inputs and no secrets. MITA-13's `release.yml` reuses it with `uses: ./.github/workflows/ci.yml`.
- **Concurrency.** A new push to a pull request cancels that pull request's running jobs. A run on `develop` is never cancelled while it runs. The group name starts with `ci-`, so it cannot collide with a group that `release.yml` defines for itself.
- **Every job** runs on `ubuntu-24.04`, has a `timeout-minutes`, and starts with `actions/checkout` (`persist-credentials: false`).

| Job | Sets up | Runs (working directory) |
|---|---|---|
| `backend` | uv, Python from `backend/.python-version`, the runner | `megoocolab-runner services run test -- uv run pytest` (`backend/`) |
| `security` | uv, Python, the runner | `make test-security` (root) |
| `frontend` | Node 22 with the npm cache | `npm ci`, `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build` (`frontend/`) |
| `release-tools` | uv, Python | `uv run --project backend pytest tools/release`, then `python tools/release/versions.py check` (root) |
| `backend-image` | uv, Python, the runner | `megoocolab-runner services run image -- uv run pytest -m docker` (`backend/`) |
| `frontend-image` | Node 22, the runner | `npm ci`, then `megoocolab-runner services run web -- npm run test:image` (`frontend/`) |
| `stack` | uv, Python, the runner | `megoocolab-runner services run stack -- uv run pytest -m stack` (`backend/`) |

The runner step, the same line in each of the five jobs that need it:

```yaml
- name: Install megoocolab-runner
  run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
```

`--system` puts the binary in `/usr/local/bin`, which is already on `PATH`.

Notes for the plan:

- **The version to pin** is the one `megoocolab-runner version` prints on the owner's machine, where every check passes today. Before writing it into `ci.yml`, confirm that the release `runner-v<version>` is public: its `checksums.txt` downloads without a token.
- **The action versions** (`actions/checkout`, `actions/setup-node`, `actions/setup-python`, `astral-sh/setup-uv`) are the current majors at build time. Confirm them, and `UV_LOCKED`, in the tools' documentation instead of from memory.
- Node is 22 because `frontend/Dockerfile` builds with `node:22-alpine`. Python comes from `backend/.python-version` (3.12).
- `release-tools` needs no full git history: `check` reads only the version files, and the tests make their own temporary repositories.
- `guard` and `plan` are not run in CI. On `develop` the version never changes, so both fail there by design. They belong to the release.

### `AGENTS.md`

One paragraph at the end of "Checks":

> CI (`.github/workflows/ci.yml`) runs all of these checks on every pull request into `develop` and on every push to it, and the Release workflow reuses it. It installs the `megoocolab-runner` version set in `MEGOO_RUNNER_VERSION` in that file. CI does not replace the checks above: run them before you push.

## Data and interfaces

- **The interface to `release.yml`:** `workflow_call` without inputs, secrets or outputs. The called jobs appear under the caller's job name, for example `tests / backend`.
- **Check names on a pull request:** `backend`, `security`, `frontend`, `release-tools`, `backend-image`, `frontend-image`, `stack`. The owner can later make them required on `develop`.
- **No secrets and no repository variables.** Every credential in the test sets is a throwaway value that is already in the repository.
- **No new configuration for the product.** `pyyaml` is a development dependency only, so the backend image does not change.

## Error handling and edge cases

- **The runner release is missing, private, or has no `services run`.** The MegooColab project's agent could not confirm that a published release has the command (MC-Q11: the checkout it read is 0.9.0 without it). The install step, or the first `services run`, then fails. In that case stop and report to the owner. Do not replace the runner with a script or with Compose steps: the owner rejected both.
- **`install.sh` is read from MegooColab's `main`,** not from the pinned tag. A change to the script could break the install step even with the same pinned version. The binary itself is still the pinned one and its checksum is checked.
- **A check that passes locally and fails on GitHub** (for example a whole-project ESLint finding, since local runs lint only changed files, or a test that leans on the local machine). Fixing it is part of this task, because the task is done only when every job is green. A test is never skipped or marked to make CI green.
- **A stale lock file.** `UV_LOCKED` makes `uv run` fail instead of rewriting `uv.lock`, and `npm ci` fails when `package-lock.json` does not match `package.json`.
- **A hung job** ends at its `timeout-minutes` (20 for most jobs, 30 for `stack`), not at GitHub's 6 hours.
- **`next build` needs the network** to download the fonts. GitHub's runners have it.
- **A failed start of a set.** The runner removes its containers after every command, also a failed one, so jobs leave nothing behind. The job's log is the place to read why.

## Testing

Test first, as `AGENTS.md` asks.

- **`backend/tests/test_workflows.py`** loads `ci.yml` with PyYAML (which reads the key `on` as `True`; a comment says so) and checks:
  - the triggers are exactly `push` and `pull_request`, both limited to `develop`, and `workflow_call`;
  - `permissions` is exactly `contents: read`;
  - the seven jobs exist, and each one's `run` lines contain its command from the table above;
  - every job that calls `megoocolab-runner` or `make test-security` has the install step, and the install step uses `MEGOO_RUNNER_VERSION`;
  - every set that a job names exists in `megoocolab.toml`;
  - no job runs `versions.py plan` or `versions.py guard`.
- **The existing suites** still pass locally with the commands of `AGENTS.md`, including the new test file inside `uv run pytest`.
- **The real proof is the pull request of this task:** it runs the seven jobs on GitHub and all are green. The run is checked with `gh pr checks`. If a job fails, the cause is fixed in this branch and the run repeated.

## Out of scope

- `release.yml`, the image publishing and the `v0.1.0` release (MITA-13).
- Branch protection on `develop` (making the seven checks required). It is a GitHub setting the owner changes by hand once the first run is green.
- Valkey and Meilisearch: they join the sets in `megoocolab.toml` with the features that use them, and CI then starts them without a change here.
- A backend linter or type checker, a Docker layer cache, a test-coverage report, and a manual (`workflow_dispatch`) trigger.
- Changes to `megoocolab-runner` or its install script.
