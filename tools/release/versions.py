"""MegooITAdmin's release rules, for the Release workflow and for whoever releases (docs/releasing.md).

    python tools/release/versions.py check    every version file agrees with VERSION

One product: MegooITAdmin, whose version is `VERSION`, kept equal in every Python package's pyproject.toml and
uv.lock and in the frontend's package.json and package-lock.json. A release is tagged vX.Y.Z.

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
# where the Python packages are: each of these directories that holds a pyproject.toml, with its uv.lock beside it
PACKAGES = ["backend", "workers/*", "gateway", "executor"]
# the uv.lock entry of the package itself, not of a dependency
SELF = ({"virtual": "."}, {"editable": "."})


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


COMMANDS = {
    "check": lambda root: ({}, check(root)),
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
