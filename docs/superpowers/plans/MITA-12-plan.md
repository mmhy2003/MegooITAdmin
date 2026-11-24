# MITA-12 plan: CI workflow (`.github/workflows/ci.yml`)

## Goal

Every pull request into `develop`, and every push to `develop`, runs the seven checks of `AGENTS.md` on GitHub, one job per check, and `release.yml` (MITA-13) can reuse the same workflow through `workflow_call`.

## Architecture

One workflow file, `.github/workflows/ci.yml`, with seven independent jobs on `ubuntu-24.04`. The jobs that need containers install the published `megoocolab-runner` at one pinned version (`MEGOO_RUNNER_VERSION`) and run the commands of `AGENTS.md` unchanged, so `megoocolab.toml` stays the only description of the services. A backend test, `backend/tests/test_workflows.py`, reads the workflow's YAML and checks its triggers, permissions, jobs and commands, because the workflow itself only runs on GitHub.

## Facts confirmed while planning (2026-11-24)

- **Runner releases.** `mmhy2003/MegooColab` is public. `runner-v0.11.0` (2026-11-18) is the first release whose notes mention `megoocolab-runner services run`; `runner-v0.12.0` (2026-11-18) is the newest and has it too. Both have `checksums.txt` and `megoocolab-runner_<ver>_linux_amd64.tar.gz`. `runner-v0.10.1` and older have **no** `services` command. `install.sh` on `main` loads (HTTP 200), accepts only `--system` and `-h/--help`, and with `MEGOO_RUNNER_VERSION` set does not call the GitHub API.
- **Action versions** (latest releases): `actions/checkout` v7.0.1, `actions/setup-node` v7.1.0, `actions/setup-python` v7.1.0, `astral-sh/setup-uv` v10.4.0. The actions/* repositories publish moving major tags (`@v7`). `astral-sh/setup-uv` is pinned to its full tag `@v10.4.0` (it does not reliably publish a moving major tag).
- **setup-uv inputs:** `enable-cache`, `cache-dependency-glob` (relative to the repository root by default). **setup-python:** `python-version-file`.
- **`UV_LOCKED`** exists since uv 0.4.25: same as `--locked`, uv fails if `uv.lock` would change.
- **`pyyaml` 6.0.4** is already in `backend/uv.lock` (through `uvicorn[standard]`), so adding it to the `dev` group adds no new package.
- `tools/release/test_versions.py` passes its own `user.name`/`user.email` to git, so it needs no git identity on the runner.
- `frontend/package.json`: `"lint": "eslint"` (whole project), `"test": "vitest run"`, `"test:image": "vitest run --config vitest.image.config.mts"`, `"build": "next build"`.

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | `pyyaml>=6.0.4` in `[dependency-groups] dev` |
| `backend/tests/test_workflows.py` | create | Checks of `ci.yml`'s text (Appendix A) |
| `.github/workflows/ci.yml` | create | The CI workflow (Appendix B) |
| `AGENTS.md` | modify | One paragraph about CI at the end of "Checks" |

`Makefile`, `megoocolab.toml`, the Compose files and `docs/releasing.md` do not change (unless step 3 finds a CI-only failure whose fix lives there; the fix must not skip or mark a test).

## Steps

### 1. The workflow tests and `ci.yml`, with pyyaml in the backend's dev group

**Files:** `backend/pyproject.toml`, `backend/uv.lock`, new `backend/tests/test_workflows.py`, new `.github/workflows/ci.yml`.

1. **Dependency.** From `backend/`: `uv add --group dev 'pyyaml>=6.0.4'`. `backend/pyproject.toml`'s `dev` group then reads `httpx`, `pytest`, `pytest-asyncio`, `pyyaml` (sorted). `uv.lock` changes only in the `megooitadmin-backend` entry's dev requirements. Check with `uv lock --check`.
2. **Tests first.** Create `backend/tests/test_workflows.py` exactly as in Appendix A.
3. **Watch them fail.** From `backend/`: `uv run pytest tests/test_workflows.py`. Expected: every test fails with `FileNotFoundError: ... .github/workflows/ci.yml`.
4. **Pick the runner version.** Run `megoocolab-runner version`. The version it prints is the one to pin (it is the one every check passes with locally). It must be **0.11.0 or newer** (0.10.x and older have no `services` command). Confirm the release is public without a token: `curl -fsSL -o /dev/null https://github.com/mmhy2003/MegooColab/releases/download/runner-v<ver>/checksums.txt` exits 0. If the local version is older than 0.11.0 or its release is not public, stop and report to the owner; do not replace the runner with a script or Compose steps (the owner rejected both).
5. **Confirm the action tags** still exist: `git ls-remote --tags https://github.com/actions/checkout v7`, same for `actions/setup-node v7`, `actions/setup-python v7`, and `git ls-remote --tags https://github.com/astral-sh/setup-uv v10.4.0`. Each prints one line.
6. **Implement.** Create `.github/workflows/ci.yml` exactly as Appendix B, with `MEGOO_RUNNER_VERSION` set to the version from 4.
7. **Pass.**
   - From `backend/`: `megoocolab-runner services run test -- uv run pytest tests/test_workflows.py`: all pass.
   - From the repository root: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest` prints nothing and exits 0. Fix whatever it reports.
   - From `backend/`: `megoocolab-runner services run test -- uv run pytest`: the whole suite passes, the new file included.

**Commit:** `ci: run every check on pull requests and pushes to develop`. Body: why (no CI today; one job per check so a failure is named on the PR; the runner is pinned so the sets in `megoocolab.toml` stay the only description of the services; `workflow_call` lets the release reuse it).

### 2. AGENTS.md says what CI runs

**File:** `AGENTS.md`. At the end of the "Checks" section, after the paragraph that ends "Never report a skipped check as passed.", add this paragraph (blank line before it):

> CI (`.github/workflows/ci.yml`) runs all of these checks on every pull request into `develop` and on every push to it, and the Release workflow reuses it. It installs the `megoocolab-runner` version set in `MEGOO_RUNNER_VERSION` in that file. CI does not replace the checks above: run them before you push.

Documentation only: no test. Check that `git diff AGENTS.md` shows only the added paragraph.

**Commit:** `docs: AGENTS.md says what CI runs and that it does not replace the local checks`.

### 3. Every CI job passes when run as CI runs it, from a clean checkout

Goal: catch, before GitHub does, failures that only show in CI: a whole-project ESLint finding (locally only changed files are linted), a test that leans on an untracked file, `node_modules`, a `.env`, or a stale lock file.

1. Make a clean copy of the committed branch: `git clone --quiet --branch <current branch> "$PWD" /tmp/mita12-ci` (outside the worktree; delete it at the end).
2. In `/tmp/mita12-ci`, with `UV_LOCKED=1` exported, run each job's commands exactly as `ci.yml` has them, in its working directory:
   - `backend` (`backend/`): `megoocolab-runner services run test -- uv run pytest`
   - `security` (root): `make test-security`
   - `frontend` (`frontend/`): `npm ci`, `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`
   - `release-tools` (root): `uv run --project backend pytest tools/release`, then `python tools/release/versions.py check`
   - `backend-image` (`backend/`): `megoocolab-runner services run image -- uv run pytest -m docker`
   - `frontend-image` (`frontend/`): `npm ci` (already done), `megoocolab-runner services run web -- npm run test:image`
   - `stack` (`backend/`): `megoocolab-runner services run stack -- uv run pytest -m stack`
3. For each failure: write or adjust a test that reproduces it where one makes sense, fix the cause in the worktree (not in `/tmp/mita12-ci`), and commit each fix on its own (`fix(<area>): …` with a body saying it showed in CI only). Never skip, mark or delete a test, and never weaken a lint rule, to make a job green. Re-clone and repeat until all seven pass.
4. Remove `/tmp/mita12-ci`.
5. If no fix was needed, there is nothing to commit; report that all seven jobs passed from a clean clone and list the commands.

## Final verification

1. From `backend/`: `megoocolab-runner services run test -- uv run pytest` passes (includes `tests/test_workflows.py`).
2. From the root: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest` prints nothing.
3. Step 3's seven job commands all pass from a clean clone.
4. **On GitHub (the real proof, at the pull request stage):** the pull request of this task into `develop` shows seven checks: `backend`, `security`, `frontend`, `release-tools`, `backend-image`, `frontend-image`, `stack`. `gh pr checks <PR> --watch` ends with all seven passing. If a job fails, read its log (`gh run view <run-id> --log-failed`), fix the cause on this branch, push, and watch again. If the install step or the first `services run` fails because of the runner itself, stop and report to the owner.

---

## Appendix A: `backend/tests/test_workflows.py`

```python
"""The GitHub Actions workflows run only on GitHub, so their text is checked here: the triggers, the permissions
and the command of each job. They need neither Docker nor a database."""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
INSTALL = "https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh"
INSTALL_STEP = "Install megoocolab-runner"

# Each job: its working directory (None for the repository root) and the commands it runs, in order.
JOBS = {
    "backend": ("backend", ["megoocolab-runner services run test -- uv run pytest"]),
    "security": (None, ["make test-security"]),
    "frontend": ("frontend", ["npm ci", "npx tsc --noEmit", "npm run lint", "npm test", "npm run build"]),
    "release-tools": (None, ["uv run --project backend pytest tools/release", "python tools/release/versions.py check"]),
    "backend-image": ("backend", ["megoocolab-runner services run image -- uv run pytest -m docker"]),
    "frontend-image": ("frontend", ["npm ci", "megoocolab-runner services run web -- npm run test:image"]),
    "stack": ("backend", ["megoocolab-runner services run stack -- uv run pytest -m stack"]),
}


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def runs(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def needs_runner(job: dict) -> bool:
    return any("megoocolab-runner services run" in line or "make test-security" in line for line in runs(job))


@pytest.fixture
def ci() -> dict:
    return workflow("ci.yml")


def test_ci_runs_on_develop_and_for_the_release(ci):
    # PyYAML reads the key `on` as True: it is a boolean in YAML 1.1.
    on = ci[True]
    assert set(on) == {"push", "pull_request", "workflow_call"}
    assert on["push"] == {"branches": ["develop"]}
    assert on["pull_request"] == {"branches": ["develop"]}
    assert on["workflow_call"] is None
    assert ci["permissions"] == {"contents": "read"}


def test_ci_has_one_job_per_check(ci):
    assert set(ci["jobs"]) == set(JOBS)
    for name, job in ci["jobs"].items():
        assert "needs" not in job, f"{name} waits for another job"


@pytest.mark.parametrize("name", JOBS)
def test_each_job_runs_its_commands_in_its_directory(ci, name):
    job = ci["jobs"][name]
    directory, commands = JOBS[name]
    assert job.get("defaults", {}).get("run", {}).get("working-directory") == directory
    lines = runs(job)
    positions = []
    for command in commands:
        found = [i for i, line in enumerate(lines) if command in line]
        assert found, f"{name} does not run {command}"
        positions.append(found[0])
    assert positions == sorted(positions), f"{name} runs its commands out of order"


@pytest.mark.parametrize("name", JOBS)
def test_each_job_runs_on_ubuntu_with_a_timeout_and_a_read_only_checkout(ci, name):
    job = ci["jobs"][name]
    assert job["runs-on"] == "ubuntu-24.04"
    assert 0 < job["timeout-minutes"] <= 30
    first = job["steps"][0]
    assert first["uses"].startswith("actions/checkout@")
    assert first["with"]["persist-credentials"] is False


def test_the_runner_version_is_pinned_once(ci):
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(ci["env"]["MEGOO_RUNNER_VERSION"]))
    assert str(ci["env"]["UV_LOCKED"]) == "1"


@pytest.mark.parametrize("name", JOBS)
def test_every_job_that_starts_services_installs_the_pinned_runner_first(ci, name):
    job = ci["jobs"][name]
    names = [step.get("name") for step in job["steps"]]
    if not needs_runner(job):
        assert INSTALL_STEP not in names
        return
    install = job["steps"][names.index(INSTALL_STEP)]
    assert INSTALL in install["run"]
    assert 'MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system' in install["run"]
    first_use = next(i for i, step in enumerate(job["steps"]) if "run" in step and needs_runner({"steps": [step]}))
    assert names.index(INSTALL_STEP) < first_use


def test_every_set_a_job_names_is_in_megoocolab_toml(ci):
    sets = tomllib.loads((ROOT / "megoocolab.toml").read_text())["services"]
    named = {name for job in ci["jobs"].values() for line in runs(job) for name in re.findall(r"services run (\S+)", line)}
    assert named == {"test", "image", "web", "stack"}
    assert named <= set(sets)


def test_ci_never_runs_the_release_only_checks(ci):
    for job in ci["jobs"].values():
        for line in runs(job):
            assert "versions.py plan" not in line
            assert "versions.py guard" not in line
            assert "release-check" not in line
```

## Appendix B: `.github/workflows/ci.yml`

Replace `0.12.0` with the version step 1.4 confirms (0.11.0 or newer). Keep the install line identical in all five jobs.

```yaml
# Every check of AGENTS.md ("Checks"), one job each. release.yml reuses this workflow (workflow_call).
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
  MEGOO_RUNNER_VERSION: "0.12.0" # the pinned megoocolab-runner; it starts the sets of megoocolab.toml
  UV_LOCKED: "1"                 # uv fails when uv.lock is out of date

jobs:
  backend:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      - uses: astral-sh/setup-uv@v10.4.0
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install megoocolab-runner
        run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
      - run: megoocolab-runner services run test -- uv run pytest

  security:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      - uses: astral-sh/setup-uv@v10.4.0
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install megoocolab-runner
        run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
      - run: make test-security

  frontend:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-node@v7
        with:
          node-version: 22 # frontend/Dockerfile builds with node:22-alpine
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npm run lint
      - run: npm test
      - run: npm run build

  release-tools:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      - uses: astral-sh/setup-uv@v10.4.0
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - run: uv run --project backend pytest tools/release
      # Not plan or guard: the version never changes on develop, so both belong to the release.
      - run: python tools/release/versions.py check

  backend-image:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      - uses: astral-sh/setup-uv@v10.4.0
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install megoocolab-runner
        run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
      - run: megoocolab-runner services run image -- uv run pytest -m docker

  frontend-image:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-node@v7
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install megoocolab-runner
        run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
      - run: npm ci
      - run: megoocolab-runner services run web -- npm run test:image

  stack:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      - uses: astral-sh/setup-uv@v10.4.0
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install megoocolab-runner
        run: curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system
      - run: megoocolab-runner services run stack -- uv run pytest -m stack
```

## Self-review

- Design decision 1 (seven checks) → Appendix B jobs, tested by `test_ci_has_one_job_per_check` and `test_each_job_runs_its_commands_in_its_directory`.
- Decision 2 (published runner, commands unchanged) and 6 (one version variable, install script with `--system`) → install step, `test_the_runner_version_is_pinned_once`, `test_every_job_that_starts_services_installs_the_pinned_runner_first`, `test_every_set_a_job_names_is_in_megoocolab_toml`.
- Decision 3 (parallel, no `needs`) → `test_ci_has_one_job_per_check`. Decision 4 (`security` job) → in `JOBS`. Decision 5 (no path filters) → the trigger test compares the whole `push`/`pull_request` value. Decision 7 (tests, pyyaml in dev) → step 1. Decision 8 (no cache of layers, no backend lint) → none added.
- Concurrency, `UV_LOCKED`, timeouts (20, `stack` 30), `persist-credentials: false`, `ubuntu-24.04`, Node 22, Python from `backend/.python-version` → Appendix B; timeouts, runner OS and checkout are tested.
- `AGENTS.md` paragraph → step 2. "Fix CI-only failures, never skip a test" → step 3 and final verification 4. Out-of-scope items (release.yml, branch protection, Valkey/Meilisearch, workflow_dispatch) are not in any step.
