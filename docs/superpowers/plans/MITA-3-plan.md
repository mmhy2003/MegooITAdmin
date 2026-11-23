# MITA-3 plan: release tooling `tools/release/versions.py` (check, plan, guard)

## Goal

Add `tools/release/versions.py` with three commands, `check`, `guard` and `plan`, covered by `pytest tools/release`, and make `make release-check`, `AGENTS.md` and `docs/releasing.md` rely on it.

## Architecture

The tool is one standard-library Python file (3.11+, `tomllib`). It is built from small functions that take the repository root, so the tests can point them at a temporary git repository: `parse`, `packages`, `places`, `check`, `guard`, `plan` and `main`. `check` reads only files on disk. `guard` and `plan` also read git tags, `git diff` and `git ls-files`. `main` finds the root with `git rev-parse --show-toplevel`, runs one command, prints the result and returns the exit code (0 for success, 1 for problems, 2 for usage). The tests run with the backend's environment: `uv run --project backend pytest tools/release`, from the repository root.

## File map

| File | Change | Responsibility |
|---|---|---|
| `tools/release/versions.py` | New (steps 1 to 3) | The three commands. The final file is in Appendix A |
| `tools/release/test_versions.py` | New (steps 1 to 3) | Tests on a temporary git repository, plus one test on the real checkout. The helpers are in Appendix B |
| `tools/release/.gitkeep` | Deleted (step 1) | |
| `Makefile` | Modified (step 4) | `release-check` loses its `@test -f tools/release/versions.py ...` line. The two `python tools/release/versions.py` lines stay |
| `backend/tests/test_makefile.py` | Modified (step 4) | `test_release_check_says_the_release_tool_is_not_in_the_repository_yet` is replaced |
| `AGENTS.md` | Modified (step 5) | The Checks "Release tools" line, and step 6 of the routine |
| `docs/releasing.md` | Modified (step 5) | Version numbers, step 6, the command block, and the workflow `plan` bullet |

Nothing else changes: no new `pyproject.toml`, no new dependency, no change to `megoocolab.toml`, `README.md`, CI or the PRD. `.pytest_cache/` and `__pycache__/` are already in `.gitignore`.

## Conventions for every step

- Write the test first, run it and watch it fail, then implement and run it again.
- Tool tests, from the repository root: `uv run --project backend pytest tools/release -v`. No service is needed.
- Backend tests (step 4 only), from `backend/`: `megoocolab-runner services run test -- uv run pytest`.
- Commit only the step's files. Never commit `.megoocolab/`. Commit subject `type(area): sentence`, a body that says why, and the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The final names, messages and signatures are in Appendix A. Steps 1 to 3 each add their part of that file. Keep every name and every message exactly as written there, because the tests compare whole lines.

---

## Steps

### 1. versions.py check: every version file, lock files included, agrees with VERSION

**Files:** create `tools/release/versions.py` and `tools/release/test_versions.py`. Delete `tools/release/.gitkeep` with `git rm tools/release/.gitkeep`.

**Test first** (`tools/release/test_versions.py`): the imports, the helpers and the `repo` fixture from Appendix B, then these tests:

- `test_parse_accepts_x_y_z_with_or_without_v`: `parse("0.1.0") == (0, 1, 0)`, `parse("v0.1.0") == (0, 1, 0)`, and `parse(" 1.2.3\r\n") == (1, 2, 3)`.
- `test_parse_rejects_what_is_not_a_release_version`, parametrized over `"dev"`, `"1.0"`, `"0.1.0-rc1"` and `""`: the result is `None`.
- `test_versions_compare_as_numbers`: `parse("0.10.0") > parse("0.9.0")`.
- `test_check_passes_when_every_place_agrees`: `check(repo) == []`.
- `test_check_names_the_place_that_differs`, parametrized over the five places. Each case changes one place to `0.2.0` and expects exactly `[f"{name} says 0.2.0, VERSION says 0.1.0: they must be equal"]`. The names are `backend/pyproject.toml` and `backend/uv.lock` (use `replace(repo, path, 'version = "0.1.0"', 'version = "0.2.0"')`), `frontend/package.json` (`write_frontend(repo, package="0.2.0")`), `frontend/package-lock.json` (`write_frontend(repo, lock="0.2.0")`) and `frontend/package-lock.json packages[""]` (`write_frontend(repo, lock_root="0.2.0")`).
- `test_check_ignores_a_dependency_version_in_uv_lock`: the fixture's lock holds `fastapi` at `9.9.9`. Expect `check(repo) == []` and `("backend/uv.lock", "0.1.0")` in `places(repo)[0]`.
- `test_check_reads_an_editable_self_entry`: `write_package(repo, "backend", source="editable")`, then `check(repo) == []`.
- `test_check_finds_more_packages`: `write_package(repo, "workers/collector")` and `write_package(repo, "gateway", version="0.2.0")`. Expect `workers/collector/pyproject.toml` and `workers/collector/uv.lock` among the names in `places(repo)[0]`, and `check(repo)` to equal the two lines for `gateway/pyproject.toml` and `gateway/uv.lock`, both saying 0.2.0.
- `test_check_skips_a_directory_without_pyproject`: create `executor/.gitkeep` and `workers/indexer/.gitkeep`. Expect `check(repo) == []`, and no name in `places(repo)[0]` starts with `executor` or `workers`.
- `test_check_reports_a_pyproject_without_uv_lock`: delete `backend/uv.lock`. Expect `["backend/uv.lock is missing: every Python package needs its own uv.lock beside its pyproject.toml"]`.
- `test_check_reports_a_uv_lock_without_its_own_entry`: write `backend/uv.lock` as `UV_LOCK_DEPENDENCY_ONLY` (Appendix B). Expect `['backend/uv.lock has no entry for the package itself (source = { virtual = "." })']`.
- `test_check_reports_a_version_that_is_not_x_y_z`, parametrized over `"dev"` and `"v0.1.0"`: write that value to `VERSION`. `_not_release(value)` is among the errors (for `dev` that is `"VERSION holds 'dev', not a release version (X.Y.Z)"`).
- `test_check_reports_a_missing_or_broken_file_as_one_line`, parametrized:
  - delete `frontend/package.json`: `["frontend/package.json is missing"]`;
  - delete `VERSION`: `["VERSION is missing"]`;
  - write `{` to `frontend/package-lock.json`: one error, starting with `frontend/package-lock.json cannot be read: `;
  - write `[project]\nname = "x"\n` to `backend/pyproject.toml`: `["backend/pyproject.toml has no project.version"]`.

  Each case also asserts `len(errors) == 1` and that no error contains `"\n"`.
- `test_check_passes_on_this_repository`: `check(REPO) == []`, and both `backend/pyproject.toml` and `backend/uv.lock` are among the names in `places(REPO)[0]`.
- CLI tests (`run(cwd, *args)` from Appendix B):
  - `test_cli_check_passes_silently`: exit 0, empty stdout and stderr.
  - `test_cli_check_fails_with_one_line_per_problem_on_stderr`: change `frontend/package.json` to 0.2.0. Expect exit 1, empty stdout, and stderr equal to the one line plus `"\n"`.
  - `test_cli_finds_the_root_from_a_subdirectory`: `run(repo / "backend", "check")` exits 0.
  - `test_cli_without_a_known_command_prints_usage`, parametrized over `[]`, `["nope"]` and `["check", "extra"]`: exit 2, and `versions.py check` is in stderr.
  - `test_cli_outside_a_git_repository_stops_with_gits_message`: in an empty `tmp_path / "outside"`, with the `GIT_CEILING_DIRECTORIES` env from `run`, expect exit 1 and `not a git repository` in stderr (lower-cased).

**Run:** `uv run --project backend pytest tools/release -v`. Expected: collection fails with `ModuleNotFoundError: No module named 'versions'`.

**Implement** in `tools/release/versions.py`: the module docstring, but with only the `check` command line (add the `guard` and `plan` lines in steps 2 and 3, and the paragraph about tags in step 2), and the constants `RELEASE`, `TAG`, `VERSION_FILE`, `PACKAGES` and `SELF`. Then `Problem`, `parse`, `_git`, `_load`, `_field`, `_version`, `_not_release`, `packages`, `_pyproject`, `_uv_lock`, `_package_json`, `_package_lock`, `places` and `check`, all as in Appendix A. `main` is as in Appendix A, with `COMMANDS = {"check": lambda root: ({}, check(root))}` for now.

**Run again:** every test passes. Also run `python tools/release/versions.py check` from the root (or `uv run --project backend python tools/release/versions.py check` if `python` is not on PATH). Expected: exit 0, no output.

**Commit:** `feat(release): versions.py check says whether every version file, lock files included, agrees with VERSION`

### 2. versions.py guard: a changed product must carry a higher version than its last tag

**Files:** `tools/release/versions.py` and `tools/release/test_versions.py`.

**Test first:** use the `tag(root, name)` and `change(root, path)` helpers from Appendix B. `PRODUCT_CHANGED` is the error from Appendix A, built in the test as:

```python
f"{', '.join(versions.PRODUCT)} changed since v0.1.0 but VERSION is still 0.1.0: bump it (e.g. {path})"
```

- `test_guard_passes_without_tags`: `guard(repo) == []`.
- `test_guard_passes_on_the_tagged_commit`: `tag(repo, "v0.1.0")`, then `guard(repo) == []`.
- `test_a_product_change_needs_a_bump`, parametrized over `backend/app/main.py`, `workers/collector/main.py`, `gateway/main.py`, `executor/main.py`, `frontend/src/page.tsx`, `caddy/Caddyfile`, `docker-compose.yml`, `.env.example` and `Makefile`. Steps: `tag(repo, "v0.1.0")`, then `change(repo, path)` (it writes the file and commits). Expect `guard(repo) == [PRODUCT_CHANGED]` with that path. Then `set_version(repo, "0.1.1")`, without committing, and expect `guard(repo) == []`.
- `test_a_change_outside_the_product_needs_no_bump`, parametrized over `docs/notes.md`, `tools/release/notes.txt`, `.github/workflows/ci.yml`, `AGENTS.md`, `README.md` and `megoocolab.toml`: after the tag and the change, `guard(repo) == []`.
- `test_a_version_lower_than_the_last_tag_is_refused`: `tag(repo, "v0.2.0")`. Expect `["VERSION says 0.1.0, lower than the last release v0.2.0"]`.
- `test_the_last_tag_is_picked_by_number`: `tag(repo, "v0.9.0")` and `tag(repo, "v0.10.0")`. Expect `versions._last_tag(repo) == "v0.10.0"`. After `set_version(repo, "0.9.5")`, `guard(repo) == ["VERSION says 0.9.5, lower than the last release v0.10.0"]`.
- `test_tags_that_are_not_release_versions_are_ignored`: `tag(repo, "v0.1.0")`, `tag(repo, "v1.0.0-rc1")` and `tag(repo, "latest")`. Expect `_last_tag(repo) == "v0.1.0"` and `guard(repo) == []`.
- `test_guard_reports_a_version_that_is_not_x_y_z`: write `dev` to `VERSION`. Expect `[_not_release("dev")]`.
- `test_cli_guard`: exit 0 with empty output on the fixture. After the tag and a change to `backend/app/main.py`: exit 1, empty stdout, and stderr equal to the `PRODUCT_CHANGED` line plus `"\n"`.

**Run:** `uv run --project backend pytest tools/release -v`. Expected: the new tests fail with `AttributeError: module 'versions' has no attribute 'guard'` (or `'PRODUCT'`), and `test_cli_guard` exits 2.

**Implement**, as in Appendix A: `PRODUCT`, `_last_tag`, `guard` and `"guard": lambda root: ({}, guard(root))` in `COMMANDS`, plus the `guard` line of the docstring and the paragraph about tags and `fetch-depth: 0`.

**Run again:** every test passes. `python tools/release/versions.py guard` in this checkout exits 0, because it has no tags.

**Commit:** `feat(release): versions.py guard refuses a changed product that still carries its last release's version`

### 3. versions.py plan: decide whether this version needs a release and is ready for one

**Files:** `tools/release/versions.py` and `tools/release/test_versions.py`.

**Test first:**

- `test_plan_before_any_release`: `plan(repo) == ({"release": "true", "version": "0.1.0"}, [])`.
- `test_plan_without_the_release_note_fails`: `git(repo, "rm", "-q", "docs/releases/v0.1.0.md")`, then commit. Expect `plan(repo)[1] == [NOTE_MISSING]`, where `NOTE_MISSING` is `"docs/releases/v0.1.0.md is missing (or not added to git): every release needs its release note"`.
- `test_a_note_only_on_disk_does_not_count`: `git(repo, "rm", "-q", "--cached", "docs/releases/v0.1.0.md")`, leaving the file on disk. Expect `[NOTE_MISSING]`.
- `test_a_staged_note_counts`: `tag(repo, "v0.1.0")` and `set_version(repo, "0.2.0")`. Write `docs/releases/v0.2.0.md` and `git add` it, without committing. Expect `({"release": "true", "version": "0.2.0"}, [])`.
- `test_a_tagged_version_without_product_change_releases_nothing`: `tag(repo, "v0.1.0")` and `change(repo, "docs/notes.md")`. Expect `({"release": "false", "version": "0.1.0"}, [])`.
- `test_a_tagged_version_with_product_change_fails`: `tag(repo, "v0.1.0")` and `change(repo, "backend/app/main.py")`. `PRODUCT_CHANGED` for that path is in `plan(repo)[1]`.
- `test_a_check_error_fails_the_plan`: `write_frontend(repo, package="0.2.0")`. `"frontend/package.json says 0.2.0, VERSION says 0.1.0: they must be equal"` is in `plan(repo)[1]`.
- `test_plan_reports_a_bad_version_once`: write `dev` to `VERSION`. `plan(repo)[1].count(_not_release("dev")) == 1`.
- `test_cli_plan_prints_two_lines`: exit 0, stdout `"release=true\nversion=0.1.0\n"`, empty stderr. After the tag and a docs change: stdout `"release=false\nversion=0.1.0\n"`.
- `test_cli_plan_failing_prints_nothing_on_stdout`: after `git rm` of the note and a commit: exit 1, `stdout == ""`, and `NOTE_MISSING` in stderr.

**Run:** `uv run --project backend pytest tools/release -v`. Expected: `AttributeError: module 'versions' has no attribute 'plan'`, and the CLI tests exit 2.

**Implement**, as in Appendix A: `NOTES`, `plan` and `"plan": plan` in `COMMANDS`, plus the `plan` line of the docstring.

**Run again:** every test passes. By hand, from the root: `check` and `guard` exit 0. `plan` exits 1 with `docs/releases/v0.1.0.md is missing (or not added to git): every release needs its release note`. That is the expected result until MITA-13.

**Commit:** `feat(release): versions.py plan says whether this version needs a release and is ready for one`

### 4. make release-check runs the release tool without the "not in the repository yet" stop

**Files:** `backend/tests/test_makefile.py` and `Makefile`.

**Test first:** in `backend/tests/test_makefile.py`, replace `test_release_check_says_the_release_tool_is_not_in_the_repository_yet` with:

```python
def test_release_check_runs_the_version_check_then_the_release_plan(workdir):
    result = make(workdir, "-n", "release-check")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["python tools/release/versions.py check", "python tools/release/versions.py plan"]
```

**Run** from `backend/`: `megoocolab-runner services run test -- uv run pytest tests/test_makefile.py -v`. Expected: the new test fails, because `make -n` also prints the `test -f tools/release/versions.py || ...` line.

**Implement:** in `Makefile`, delete the line `@test -f tools/release/versions.py || { echo "make release-check: tools/release/versions.py is not in the repository yet." >&2; exit 1; }` under `release-check:`. Keep the two `python tools/release/versions.py` lines, the help text and `.PHONY` as they are.

**Run again:** `megoocolab-runner services run test -- uv run pytest` from `backend/`. The whole backend suite passes. From the root, `make release-check` runs `check` (which passes), then stops at `plan` with the `docs/releases/v0.1.0.md is missing` line and a non-zero exit. That is expected before the first release. Report it as expected, not as passed.

**Commit:** `chore(make): make release-check runs the release tool now that it is in the repository`

### 5. Docs: the before-merge check is the tool's tests and check, and check reads the lock files

**Files:** `AGENTS.md` and `docs/releasing.md`. Use the exact texts in Appendix C. No test applies, because these are documents. Check them with `git diff` and with `rg -n 'by hand|git diff --cached' AGENTS.md docs/releasing.md`, which must find nothing about the lock files.

**Commit:** `docs: releases rely on versions.py for the lock files, and the before-merge check is the tool's tests and check`

---

## Final verification

From the repository root:

```bash
uv run --project backend pytest tools/release -v          # every test passes
python tools/release/versions.py check; echo exit=$?      # exit=0, no output
python tools/release/versions.py guard; echo exit=$?      # exit=0, no output (no tags yet)
python tools/release/versions.py plan; echo exit=$?       # exit=1: docs/releases/v0.1.0.md is missing ... (expected until MITA-13)
python tools/release/versions.py; echo exit=$?            # exit=2, usage on stderr
make release-check; echo exit=$?                          # check passes, then stops at plan with the same line (expected)
```

If `python` is not on PATH, use `uv run --project backend python tools/release/versions.py ...` instead.

From `backend/`: `megoocolab-runner services run test -- uv run pytest`, which passes.

Skipped, and to be reported as skipped: the frontend, image and stack checks (nothing they cover changes), and `make test-security` (the security suites are not in the repository yet).

---

## Appendix A: `tools/release/versions.py` (final)

```python
"""MegooITAdmin's release rules, for the Release workflow and for whoever releases (docs/releasing.md).

    python tools/release/versions.py check    every version file agrees with VERSION
    python tools/release/versions.py guard    a product that changed since its last tag carries a higher version
    python tools/release/versions.py plan     whether this version needs a release (key=value lines, for $GITHUB_OUTPUT)

One product: MegooITAdmin, whose version is `VERSION`, kept equal in every Python package's pyproject.toml and
uv.lock and in the frontend's package.json and package-lock.json. A release is tagged vX.Y.Z.

guard and plan read the tags. A checkout without them (a shallow clone) looks like a first release, so the Release
workflow must fetch the whole history (fetch-depth: 0).

Standard library only, Python 3.11 or newer (tomllib).
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
TAG = "v"
VERSION_FILE = "VERSION"
NOTES = "docs/releases"
# where the Python packages are: each of these directories that holds a pyproject.toml, with its uv.lock beside it
PACKAGES = ["backend", "workers/*", "gateway", "executor"]
# the uv.lock entry of the package itself, not of a dependency
SELF = ({"virtual": "."}, {"editable": "."})
# what MegooITAdmin is made of: a change here since its last release needs a new version
PRODUCT = [
    "backend", "workers", "gateway", "executor", "frontend", "caddy",
    "docker-compose.yml", ".env.example", "Makefile", "VERSION",
]


class Problem(Exception):
    """A file that is missing, cannot be parsed or has no version: one line of the report, not a traceback."""


def parse(version: str) -> tuple[int, int, int] | None:
    """A release version is exactly X.Y.Z (a leading v allowed); anything else (dev, 1.0, 0.1.0-rc1) is not one."""
    m = RELEASE.match(version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _load(root: Path, path: str, load):
    try:
        return load((root / path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Problem(f"{path} is missing") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Problem(f"{path} cannot be read: {e}") from None


def _field(path: str, data, label: str, *keys: str) -> str:
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    if not isinstance(data, str):
        raise Problem(f"{path} has no {label}")
    return data


def _version(root: Path) -> str:
    try:
        return (root / VERSION_FILE).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise Problem(f"{VERSION_FILE} is missing") from None
    except (OSError, UnicodeDecodeError) as e:
        raise Problem(f"{VERSION_FILE} cannot be read: {e}") from None


def _not_release(version: str) -> str:
    return f"VERSION holds {version!r}, not a release version (X.Y.Z)"


def packages(root: Path) -> list[str]:
    """The Python packages. A directory without a pyproject.toml (only .gitkeep) is not in the repository yet."""
    found = []
    for pattern in PACKAGES:
        directories = sorted(root.glob(pattern)) if "*" in pattern else [root / pattern]
        found += [d.relative_to(root).as_posix() for d in directories if (d / "pyproject.toml").is_file()]
    return found


def _pyproject(path: str, data) -> list[tuple[str, str]]:
    return [(path, _field(path, data, "project.version", "project", "version"))]


def _uv_lock(path: str, data) -> list[tuple[str, str]]:
    for package in data.get("package", []):
        if isinstance(package, dict) and package.get("source") in SELF:
            return [(path, _field(path, package, "version in its own entry", "version"))]
    raise Problem(f'{path} has no entry for the package itself (source = {{ virtual = "." }})')


def _package_json(path: str, data) -> list[tuple[str, str]]:
    return [(path, _field(path, data, "version", "version"))]


def _package_lock(path: str, data) -> list[tuple[str, str]]:
    return [
        (path, _field(path, data, "version", "version")),
        (f'{path} packages[""]', _field(path, data, 'packages[""].version', "packages", "", "version")),
    ]


def places(root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Every place besides VERSION that holds the version, as (name, version), and one error per unreadable file."""
    files, errors = [], []
    for package in packages(root):
        files.append((f"{package}/pyproject.toml", tomllib.loads, _pyproject))
        if (root / package / "uv.lock").is_file():
            files.append((f"{package}/uv.lock", tomllib.loads, _uv_lock))
        else:
            errors.append(f"{package}/uv.lock is missing: every Python package needs its own uv.lock beside its pyproject.toml")
    files += [("frontend/package.json", json.loads, _package_json), ("frontend/package-lock.json", json.loads, _package_lock)]
    found = []
    for path, load, read in files:
        try:
            found += read(path, _load(root, path, load))
        except Problem as e:
            errors.append(str(e))
    return found, errors


def check(root: Path) -> list[str]:
    """Reads the files on disk only (no git), so it works before the release commit is made."""
    try:
        version = _version(root)
    except Problem as e:
        return [str(e)]
    found, errors = places(root)
    errors += [f"{name} says {said}, VERSION says {version}: they must be equal" for name, said in found if said != version]
    if parse(version) is None or version.startswith(TAG):
        errors.append(_not_release(version))
    return errors


def _last_tag(root: Path) -> str | None:
    tags = [t for t in _git(root, "tag", "--list", f"{TAG}*").split() if parse(t.removeprefix(TAG))]
    return max(tags, key=lambda t: parse(t.removeprefix(TAG)), default=None)


def guard(root: Path) -> list[str]:
    """A product that changed since its last tag (HEAD against the tag) must carry a higher version."""
    try:
        version = _version(root)
    except Problem as e:
        return [str(e)]
    current = parse(version)
    if current is None:
        return [_not_release(version)]
    last = _last_tag(root)
    if last is None:
        return []  # the first release: nothing to compare with
    if current < parse(last):
        return [f"VERSION says {version}, lower than the last release {last}"]
    if current > parse(last):
        return []
    changed = _git(root, "diff", "--name-only", last, "HEAD", "--", *PRODUCT).splitlines()
    if changed:
        return [f"{', '.join(PRODUCT)} changed since {last} but VERSION is still {version}: bump it (e.g. {changed[0]})"]
    return []


def plan(root: Path) -> tuple[dict[str, str], list[str]]:
    """Whether VERSION needs a release (no tag vVERSION yet), and the errors that stop it."""
    errors = check(root)
    errors += [e for e in guard(root) if e not in errors]
    try:
        version = _version(root)
    except Problem:
        return {}, errors
    release = not _git(root, "tag", "--list", f"{TAG}{version}").strip()
    if release and parse(version):
        note = f"{NOTES}/{TAG}{version}.md"
        if not _git(root, "ls-files", "--", note).strip():  # the index: a staged note counts, one only on disk not
            errors.append(f"{note} is missing (or not added to git): every release needs its release note")
    return {"release": "true" if release else "false", "version": version}, errors


COMMANDS = {
    "check": lambda root: ({}, check(root)),
    "guard": lambda root: ({}, guard(root)),
    "plan": plan,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    except subprocess.CalledProcessError as e:
        print(e.stderr.strip(), file=sys.stderr)
        return 1
    outputs, errors = COMMANDS[argv[0]](root)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1  # nothing on stdout, so $GITHUB_OUTPUT never gets half a plan
    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## Appendix B: test helpers and fixture (`tools/release/test_versions.py`, top of file)

```python
"""versions.py on a temporary git repository, and check on this checkout. Run from the repository root:
uv run --project backend pytest tools/release"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import versions
from versions import _not_release, check, parse, places

TOOL = Path(__file__).resolve().parent / "versions.py"
REPO = Path(__file__).resolve().parents[2]

PYPROJECT = '[project]\nname = "{name}"\nversion = "{version}"\n'
UV_LOCK = """version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "fastapi"
version = "9.9.9"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "{name}"
version = "{version}"
source = {{ {source} = "." }}
"""
UV_LOCK_DEPENDENCY_ONLY = """version = 1
revision = 3

[[package]]
name = "fastapi"
version = "9.9.9"
source = { registry = "https://pypi.org/simple" }
"""


def git(root: Path, *args: str) -> str:
    config = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    return subprocess.run(["git", "-C", str(root), *config, *args], check=True, capture_output=True, text=True).stdout


def commit(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def tag(root: Path, name: str) -> None:
    git(root, "tag", name)


def change(root: Path, path: str) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text((file.read_text() if file.exists() else "") + "changed\n")
    commit(root, f"change {path}")


def replace(root: Path, path: str, old: str, new: str) -> None:
    file = root / path
    assert old in file.read_text()
    file.write_text(file.read_text().replace(old, new, 1))


def write_package(root: Path, directory: str, version: str = "0.1.0", source: str = "virtual") -> None:
    path = root / directory
    path.mkdir(parents=True, exist_ok=True)
    name = directory.replace("/", "-")
    (path / "pyproject.toml").write_text(PYPROJECT.format(name=name, version=version))
    (path / "uv.lock").write_text(UV_LOCK.format(name=name, version=version, source=source))


def write_frontend(root: Path, package: str = "0.1.0", lock: str = "0.1.0", lock_root: str = "0.1.0") -> None:
    path = root / "frontend"
    path.mkdir(parents=True, exist_ok=True)
    name = "megooitadmin-frontend"
    (path / "package.json").write_text(json.dumps({"name": name, "version": package, "private": True}, indent=2))
    lockfile = {
        "name": name, "version": lock, "lockfileVersion": 3, "requires": True,
        "packages": {"": {"name": name, "version": lock_root}, "node_modules/next": {"version": "16.4.6"}},
    }
    (path / "package-lock.json").write_text(json.dumps(lockfile, indent=2))


def set_version(root: Path, version: str) -> None:
    """Every place of the fixture at version, on disk only (as in step 4 of the routine)."""
    (root / "VERSION").write_text(f"{version}\n")
    write_package(root, "backend", version)
    write_frontend(root, version, version, version)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    set_version(root, "0.1.0")
    (root / "backend" / "app").mkdir()
    (root / "backend" / "app" / "main.py").write_text("app = None\n")
    (root / "docs" / "releases").mkdir(parents=True)
    (root / "docs" / "releases" / "v0.1.0.md").write_text("MegooITAdmin 0.1.0.\n")
    commit(root, "initial")
    return root


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    env.pop("GIT_DIR", None)
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
```

Notes:
- `import versions` works because pytest's default `prepend` import mode puts `tools/release/` (which has no `__init__.py`) on `sys.path`. No pytest configuration is read from `backend/pyproject.toml`, because the tests run from the root.
- In `run`, `GIT_CEILING_DIRECTORIES` stops git from finding a parent repository. This matters for the outside-a-repository test. For the `repo` subdirectory test, `cwd.parent` is `repo` itself, which is still found.

## Appendix C: document texts (step 5)

### `AGENTS.md`

**Checks.** Replace the bullet `- **Release tools**: \`make release-check\`. It runs \`python tools/release/versions.py check\` and \`plan\`.` with:

```markdown
- **Release tools** (repository root): `uv run --project backend pytest tools/release`, then
  `python tools/release/versions.py check`. `make release-check` runs `check` and `plan` and belongs to a release
  (step 6 below), because `plan` passes only there.
```

**Step 6 of "When the owner says release".** Replace the whole item with:

```markdown
6. **Check:** `git add` the changed files, then `make release-check`. It runs
   `python tools/release/versions.py check` (every file in the table above, the lock files included, carries the
   same version) and `python tools/release/versions.py plan` (the version went up and the release note is in
   git). Both must pass.
```

### `docs/releasing.md`

**Version numbers.** Directly after the version table, add:

```markdown
`python tools/release/versions.py check` compares every file of this table, the lock files included, with
`VERSION`.
```

Then replace the paragraph that starts `If the product changed since its last tag` with:

```markdown
If the product changed since its last tag, it must carry a new, higher version. The product is `backend`,
`workers`, `gateway`, `executor`, `frontend`, `caddy`, `docker-compose.yml`, `.env.example`, `Makefile` and
`VERSION`. A change anywhere else (`docs/`, `tools/`, `.github/`, `AGENTS.md`, `README.md`, `megoocolab.toml`)
needs none. `python tools/release/versions.py guard` runs this rule alone, and `plan` includes it. The release
tooling (`tools/release/versions.py` and the Release workflow) refuses anything else. The reason: servers that
follow `latest` would otherwise get a lower version, or a changed product under a version number they already run.
```

**Step 6 of the routine.** Replace the whole item with:

```markdown
6. **Check:** stage the changed files, then run `make release-check`. It runs `python tools/release/versions.py
   check` (all files of the table, the lock files included, carry the same version) and
   `python tools/release/versions.py plan` (the version went up and the note is in git). Both must pass.
```

**Command block.** Under `# 6. Check`, delete the line `git diff --cached`. Keep the other lines.

**What the workflow does.** At the end of the `plan` bullet, add the sentence: `A version that already has its tag, with no change to the product, releases nothing: plan prints release=false and the other jobs are skipped.` Write `plan` and `release=false` in backticks.
