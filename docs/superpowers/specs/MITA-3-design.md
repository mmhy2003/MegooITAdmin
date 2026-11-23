# MITA-3 design: release tooling `tools/release/versions.py` (check, plan, guard)

## Goal

After this task the repository can check its own release rules. `python tools/release/versions.py check` says whether every version file agrees, `guard` says whether a changed product carries a higher version, and `plan` says whether the current version needs a release and is ready for one. The Release workflow (MITA-13) and CI (MITA-12) build on these three commands.

## What the repository looks like today

- `tools/release/` holds only `.gitkeep`. There are no git tags and no file in `docs/releases/` except `.gitkeep`.
- The version `0.1.0` is in `VERSION`, `backend/pyproject.toml`, `backend/uv.lock` (the entry with `source = { virtual = "." }`), `frontend/package.json` and twice in `frontend/package-lock.json` (`version` and `packages[""].version`).
- `workers/*`, `gateway/` and `executor/` hold only `.gitkeep`, so they have no `pyproject.toml` yet.
- The Makefile already has `release-check`. It stops with "not in the repository yet" while the tool is missing, then runs `check` and `plan`.
- `AGENTS.md` and `docs/releasing.md` say the tool does not read the lock files and tell the reader to check them by hand. The task says the tool reads them.

## Decisions

Answers from the owner:

1. **`make release-check` is a release-time check.** It stays `check` then `plan`, as the PRD says, and is run in step 6 of the release routine. On a work branch `plan` is expected to fail, because the version never changes there. The before-merge check in `AGENTS.md` becomes the tool's tests and `check`, the same two commands CI will run. Rejected: a `release-check` that runs tests and `check` only, and a second Makefile target.
2. **A version that already has its tag, with no change to the product, releases nothing.** `plan` exits 0 and prints `release=false`, so a second run of a finished release or a documentation-only push to `main` stays green. Rejected: failing in that case.

Decisions I made (say so if you want them changed):

3. **`guard` is a command of its own, and `plan` also runs it.** The task asks for three commands. `plan` runs `check` and `guard` first, so one command decides a release, as in MegooColab and MegooArti.
4. **`plan` prints `release=true|false` and `version=X.Y.Z`.** MegooColab prints `app=…` and `app_version=…` because it has two products. MegooITAdmin has one, so the names are shorter. MITA-13 reads these two lines.
5. **Python packages are found, not listed one by one.** The tool looks in `backend`, `workers/*`, `gateway` and `executor`, and reads each `pyproject.toml` it finds there. A directory without one is not in the repository yet and is skipped. Workers, the gateway and the executor are then checked from the day they get a `pyproject.toml`, with no change to the tool.
6. **A `pyproject.toml` without a `uv.lock` beside it is an error.** The PRD gives every Python package its own lock file. If a later task uses another layout (for example one shared lock), that task changes this rule.
7. **The product is these paths:** `backend`, `workers`, `gateway`, `executor`, `frontend`, `caddy`, `docker-compose.yml`, `.env.example`, `Makefile` and `VERSION`. A change in any of them since the last tag needs a higher version. `docs/`, `tools/`, `.github/`, `AGENTS.md`, `README.md` and `megoocolab.toml` do not. The Makefile is included because `make up` is how a person runs the product.
8. **The "check the lock files by hand" sentences are removed** from `AGENTS.md` and `docs/releasing.md`, because `check` now reads the lock files. This differs from PRD §3.10 step 6, which still says to check them by hand.
9. **The Makefile's "not in the repository yet" line for `release-check` is removed.** The tool is now there, so the line can never fire in the repository.
10. **The tests run with the backend's Python environment:** `uv run --project backend pytest tools/release`, from the repository root. The tool needs only the standard library, and the backend environment already has pytest and Python 3.12. No new project file or dependency is added. Rejected: a `pyproject.toml` at the root or in `tools/release` only to get pytest.
11. **The tool stays one file with no dependencies** (Python 3.11 or newer, for `tomllib`), written like MegooColab's and MegooArti's `versions.py`.

## Architecture

| File | Change |
|---|---|
| `tools/release/versions.py` | New. The three commands |
| `tools/release/test_versions.py` | New. Tests on a temporary git repository |
| `tools/release/.gitkeep` | Deleted |
| `Makefile` | `release-check` loses its "not in the repository yet" line. The two commands stay |
| `backend/tests/test_makefile.py` | The "not in the repository yet" test for `release-check` is replaced by one that expects the two commands |
| `AGENTS.md` | Checks and step 6 (see below) |
| `docs/releasing.md` | Version numbers, step 6, the command block and the workflow section (see below) |

### `tools/release/versions.py`

Small functions, each taking the repository root, so the tests can point them at a temporary repository:

| Function | Does |
|---|---|
| `parse(version)` | `X.Y.Z` (a leading `v` allowed) as three integers, or `None`. `dev`, `1.0` and `0.1.0-rc1` are not release versions. Versions compare as numbers, so 0.10.0 is higher than 0.9.0 |
| `places(root)` | Every place that holds the version besides `VERSION`, each with a name for messages and the version found there |
| `check(root)` | A list of errors: a place that disagrees with `VERSION`, or a `VERSION` that is not `X.Y.Z` |
| `guard(root)` | A list of errors from the guard rule |
| `plan(root)` | The two output values, and the errors of `check`, `guard` and the release note |
| `main(argv)` | Finds the root with `git rev-parse --show-toplevel`, runs one command, prints, and returns the exit code |

**Places read by `check`:**

| Place | Field |
|---|---|
| `<package>/pyproject.toml`, for each package found in `backend`, `workers/*`, `gateway`, `executor` | `[project].version` |
| `<package>/uv.lock` | `version` of the `[[package]]` entry whose `source` is the package itself (`virtual = "."` or `editable = "."`). Versions of dependencies are ignored |
| `frontend/package.json` | `version` |
| `frontend/package-lock.json` | `version` and `packages[""].version` |

`VERSION`, `frontend/package.json` and `frontend/package-lock.json` must exist. `check` reads the files on disk and does not use git, so it works before the release commit is made.

**The guard rule** (`guard`, and inside `plan`):

1. The last tag is the highest tag `vX.Y.Z`. Tags that are not release versions (for example `v1.0.0-rc1`) are ignored. With no tag there is nothing to compare, and the guard passes. That is the first release.
2. A version lower than the last tag is an error.
3. A version higher than the last tag passes.
4. A version equal to the last tag passes only if `git diff --name-only <tag> HEAD` shows no change in the product paths of decision 7. Otherwise the error names the first changed path.

**`plan`:**

1. Collects the errors of `check` and `guard`.
2. A release is needed when no tag `v<VERSION>` exists.
3. When a release is needed, `docs/releases/v<VERSION>.md` must be known to git (`git ls-files`). A staged file counts, which fits step 6 of the routine. A file that is only on disk does not. The note's content is not checked.
4. With no errors it prints the two lines and exits 0. With errors it prints nothing on stdout, so `$GITHUB_OUTPUT` never gets half a plan.

### Documents

`AGENTS.md`:

- **Checks**, the "Release tools" line becomes: from the repository root, `uv run --project backend pytest tools/release`, then `python tools/release/versions.py check`. A second sentence says `make release-check` runs `check` and `plan` and belongs to a release (step 6), because `plan` passes only there.
- **Step 6** keeps `check` and `plan`, says `make release-check` runs both, and says `check` reads the lock files too. The "check the lock files by hand" sentence goes.

`docs/releasing.md`, with the same rules in longer form:

- **Version numbers**: `check` compares every file of the table with `VERSION`. The guard paragraph names the product paths, and says `versions.py guard` runs the rule alone and `plan` includes it.
- **Step 6** and the command block: the by-hand sentence and the `git diff --cached` line go.
- **What the workflow does**, `plan`: one more sentence. A version that already has its tag, with no change to the product, releases nothing: `plan` prints `release=false` and the other jobs are skipped.

`README.md` and `megoocolab.toml` do not change. The tests need no service.

## Data and interfaces

```text
python tools/release/versions.py check    every version file agrees with VERSION
python tools/release/versions.py guard    a product that changed since its last tag carries a higher version
python tools/release/versions.py plan     whether this version needs a release (key=value lines, for $GITHUB_OUTPUT)
```

| Command | Exit 0 | Exit 1 |
|---|---|---|
| `check` | Prints nothing | One line per problem on stderr |
| `guard` | Prints nothing | One line per problem on stderr |
| `plan` | `release=true` or `release=false`, then `version=X.Y.Z`, on stdout | One line per problem on stderr, nothing on stdout |

Any other command, or none, prints the usage text on stderr and exits 2.

Error lines name the file and the fix, for example:

```text
backend/uv.lock says 0.1.0, VERSION says 0.2.0: they must be equal
VERSION holds 'dev', not a release version (X.Y.Z)
VERSION says 0.1.0, lower than the last release v0.2.0
backend, workers, … changed since v0.1.0 but VERSION is still 0.1.0: bump it (e.g. backend/app/main.py)
docs/releases/v0.2.0.md is missing (or not added to git): every release needs its release note
```

`make release-check` runs `python tools/release/versions.py check`, then `plan`.

## Error handling and edge cases

- **A file that is missing, cannot be parsed or has no version field** gives one error line that names the file. It does not give a traceback.
- **A `uv.lock` with no entry for the package itself** is an error that names the lock file.
- **On this branch and on `develop` today**, `check` and `guard` pass, and `plan` fails with "docs/releases/v0.1.0.md is missing". That is correct until the first release (MITA-13), so `make release-check` fails here. The implementer reports it as expected, not as passed.
- **After `v0.1.0`, on a work branch**, `guard` and `plan` fail as soon as a product file changes, because the version stays the same there. This is why they are release-time checks (decision 1).
- **A version that already has its tag:** with no product change `plan` prints `release=false`. With a product change `plan` fails through the guard.
- **Changes that are not committed.** The guard compares the tag with `HEAD`, as MegooColab's does. The version itself is read from disk. In step 6 the merge is already committed and the new version is on disk, so the guard sees both.
- **A checkout without tags** (a shallow clone) looks like a first release: the guard passes and `plan` says `release=true`. The Release workflow must fetch the full history (`fetch-depth: 0`). That is MITA-13's job, and the tool's docstring says so.
- **Outside a git repository** the tool stops with git's own message.
- **`python` is not on PATH** on some machines (only `python3`). The documented commands stay `python …`, as in the PRD and the Makefile. `uv run --project backend python tools/release/versions.py …` runs the same thing with the backend's Python 3.12.
- **Windows line endings** in `VERSION` do not matter: the value is stripped before it is compared.

## Testing

Tests are written first and seen failing, then made to pass.

**`uv run --project backend pytest tools/release`** (`tools/release/test_versions.py`). A fixture builds a temporary git repository with `VERSION`, a backend `pyproject.toml` and `uv.lock` (with one dependency at another version), the frontend's two files, a release note and one commit.

- `parse`: accepts `0.1.0` and `v0.1.0`, rejects `dev`, `1.0` and `0.1.0-rc1`, and orders 0.10.0 above 0.9.0.
- `check`:
  - passes when every place agrees;
  - names the place that differs, once for each of the five places;
  - ignores a dependency's version in `uv.lock`;
  - finds and checks a second package (`workers/collector`, `gateway`);
  - skips a directory that holds only `.gitkeep`;
  - reports a `pyproject.toml` without `uv.lock`, a `uv.lock` without its own entry, a `VERSION` that is not `X.Y.Z`, and a missing or broken file, each as one line.
- `guard`:
  - passes with no tags;
  - a product change after `v0.1.0` needs a bump, for several of the product paths, and bumping clears it;
  - a change in `docs/` or `tools/` alone needs none;
  - a version lower than the last tag is refused;
  - the last tag is picked by number (`v0.10.0` over `v0.9.0`), and tags that are not release versions are ignored.
- `plan`:
  - before any release, with the note in git: `release=true` and the version;
  - a missing note fails and names its path; a note that is only on disk fails, a staged one passes;
  - a tagged version with no product change: `release=false`;
  - a tagged version with a product change fails;
  - an error from `check` fails the plan.
- The commands, run as a subprocess inside the temporary repository: exit codes 0, 1 and 2, errors on stderr, the two `plan` lines on stdout, and an empty stdout when `plan` fails.
- The real repository: `check` passes on this checkout, and the backend's `pyproject.toml` and `uv.lock` are among the places read. This catches a broken search for packages.

**`megoocolab-runner services run test -- uv run pytest`** (from `backend/`), because `test_makefile.py` changes: `make -n release-check` prints `python tools/release/versions.py check` and then `python tools/release/versions.py plan`, and nothing else.

**By hand, from the repository root:** `python tools/release/versions.py check` and `guard` exit 0; `plan` exits 1 and names `docs/releases/v0.1.0.md`; `make release-check` stops at `plan` with the same message.

The frontend, stack and security checks are not affected by this task. The frontend and stack checks are skipped because nothing they cover changes, and the security suites are not in the repository yet. The finish report says so.

## Out of scope

- `ci.yml` and its `release-tools` job (MITA-12).
- `release.yml`, the release note `docs/releases/v0.1.0.md` and the `v0.1.0` release (MITA-13).
- A command that writes the new version into the files. Step 4 of the routine stays an edit by hand.
- Checking the content or the shape of a release note.
- `pyproject.toml` and `uv.lock` for the workers, the gateway and the executor. Their own tasks add them, and the tool then reads them.
- Any change to the PRD text.
