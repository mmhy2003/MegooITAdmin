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


def run(cwd: Path, *args: str, ceiling: Path | None = None) -> subprocess.CompletedProcess[str]:
    """git looks for the repository upward from cwd, but never in ceiling (cwd.parent by default) or above it."""
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(ceiling or cwd.parent)}
    env.pop("GIT_DIR", None)
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def names(root: Path) -> list[str]:
    return [name for name, _ in places(root)[0]]


def test_parse_accepts_x_y_z_with_or_without_v():
    assert parse("0.1.0") == (0, 1, 0)
    assert parse("v0.1.0") == (0, 1, 0)
    assert parse(" 1.2.3\r\n") == (1, 2, 3)


@pytest.mark.parametrize("version", ["dev", "1.0", "0.1.0-rc1", ""])
def test_parse_rejects_what_is_not_a_release_version(version):
    assert parse(version) is None


def test_versions_compare_as_numbers():
    assert parse("0.10.0") > parse("0.9.0")


def test_check_passes_when_every_place_agrees(repo):
    assert check(repo) == []


@pytest.mark.parametrize(
    "name, edit",
    [
        ("backend/pyproject.toml", lambda r: replace(r, "backend/pyproject.toml", 'version = "0.1.0"', 'version = "0.2.0"')),
        ("backend/uv.lock", lambda r: replace(r, "backend/uv.lock", 'version = "0.1.0"', 'version = "0.2.0"')),
        ("frontend/package.json", lambda r: write_frontend(r, package="0.2.0")),
        ("frontend/package-lock.json", lambda r: write_frontend(r, lock="0.2.0")),
        ('frontend/package-lock.json packages[""]', lambda r: write_frontend(r, lock_root="0.2.0")),
    ],
)
def test_check_names_the_place_that_differs(repo, name, edit):
    edit(repo)
    assert check(repo) == [f"{name} says 0.2.0, VERSION says 0.1.0: they must be equal"]


def test_check_ignores_a_dependency_version_in_uv_lock(repo):
    assert "9.9.9" in (repo / "backend" / "uv.lock").read_text()
    assert check(repo) == []
    assert ("backend/uv.lock", "0.1.0") in places(repo)[0]


def test_check_reads_an_editable_self_entry(repo):
    write_package(repo, "backend", source="editable")
    assert check(repo) == []


def test_check_finds_more_packages(repo):
    write_package(repo, "workers/collector")
    write_package(repo, "gateway", version="0.2.0")
    assert {"workers/collector/pyproject.toml", "workers/collector/uv.lock"} <= set(names(repo))
    assert check(repo) == [
        "gateway/pyproject.toml says 0.2.0, VERSION says 0.1.0: they must be equal",
        "gateway/uv.lock says 0.2.0, VERSION says 0.1.0: they must be equal",
    ]


def test_check_skips_a_directory_without_pyproject(repo):
    for directory in ["executor", "workers/indexer"]:
        (repo / directory).mkdir(parents=True)
        (repo / directory / ".gitkeep").write_text("")
    assert check(repo) == []
    assert not [name for name in names(repo) if name.startswith(("executor", "workers"))]


def test_check_reports_a_pyproject_without_uv_lock(repo):
    (repo / "backend" / "uv.lock").unlink()
    assert check(repo) == ["backend/uv.lock is missing: every Python package needs its own uv.lock beside its pyproject.toml"]


def test_check_reports_a_uv_lock_without_its_own_entry(repo):
    (repo / "backend" / "uv.lock").write_text(UV_LOCK_DEPENDENCY_ONLY)
    assert check(repo) == ['backend/uv.lock has no entry for the package itself (source = { virtual = "." })']


@pytest.mark.parametrize("value", ["dev", "v0.1.0"])
def test_check_reports_a_version_that_is_not_x_y_z(repo, value):
    (repo / "VERSION").write_text(f"{value}\n")
    assert _not_release(value) in check(repo)
    assert _not_release("dev") == "VERSION holds 'dev', not a release version (X.Y.Z)"


def _write(path: str, text: str):
    return lambda r: (r / path).write_text(text)


@pytest.mark.parametrize(
    "edit, expected",
    [
        (lambda r: (r / "frontend" / "package.json").unlink(), "frontend/package.json is missing"),
        (lambda r: (r / "VERSION").unlink(), "VERSION is missing"),
        (_write("frontend/package-lock.json", "{"), "frontend/package-lock.json cannot be read: "),
        (_write("backend/pyproject.toml", '[project]\nname = "x"\n'), "backend/pyproject.toml has no project.version"),
    ],
    ids=["package.json missing", "VERSION missing", "package-lock.json broken", "pyproject without version"],
)
def test_check_reports_a_missing_or_broken_file_as_one_line(repo, edit, expected):
    edit(repo)
    errors = check(repo)
    assert len(errors) == 1
    assert errors[0].startswith(expected)
    if not expected.endswith(": "):
        assert errors == [expected]
    assert not [error for error in errors if "\n" in error]


def test_check_passes_on_this_repository():
    assert check(REPO) == []
    assert {"backend/pyproject.toml", "backend/uv.lock"} <= set(names(REPO))


def test_cli_check_passes_silently(repo):
    result = run(repo, "check")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_cli_check_fails_with_one_line_per_problem_on_stderr(repo):
    write_frontend(repo, package="0.2.0")
    result = run(repo, "check")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "frontend/package.json says 0.2.0, VERSION says 0.1.0: they must be equal\n"


def test_cli_finds_the_root_from_a_subdirectory(repo):
    result = run(repo / "backend", "check", ceiling=repo.parent)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("args", [[], ["nope"], ["check", "extra"]])
def test_cli_without_a_known_command_prints_usage(repo, args):
    result = run(repo, *args)
    assert result.returncode == 2
    assert "versions.py check" in result.stderr


def test_cli_outside_a_git_repository_stops_with_gits_message(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    result = run(outside, "check")
    assert result.returncode == 1
    assert "not a git repository" in result.stderr.lower()


def product_changed(path: str) -> str:
    return f"{', '.join(versions.PRODUCT)} changed since v0.1.0 but VERSION is still 0.1.0: bump it (e.g. {path})"


def test_guard_passes_without_tags(repo):
    assert versions.guard(repo) == []


def test_guard_passes_on_the_tagged_commit(repo):
    tag(repo, "v0.1.0")
    assert versions.guard(repo) == []


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/main.py", "workers/collector/main.py", "gateway/main.py", "executor/main.py",
        "frontend/src/page.tsx", "caddy/Caddyfile", "docker-compose.yml", ".env.example", "Makefile",
    ],
)
def test_a_product_change_needs_a_bump(repo, path):
    tag(repo, "v0.1.0")
    change(repo, path)
    assert versions.guard(repo) == [product_changed(path)]
    set_version(repo, "0.1.1")
    assert versions.guard(repo) == []


@pytest.mark.parametrize(
    "path", ["docs/notes.md", "tools/release/notes.txt", ".github/workflows/ci.yml", "AGENTS.md", "README.md", "megoocolab.toml"]
)
def test_a_change_outside_the_product_needs_no_bump(repo, path):
    tag(repo, "v0.1.0")
    change(repo, path)
    assert versions.guard(repo) == []


def test_a_version_lower_than_the_last_tag_is_refused(repo):
    tag(repo, "v0.2.0")
    assert versions.guard(repo) == ["VERSION says 0.1.0, lower than the last release v0.2.0"]


def test_the_last_tag_is_picked_by_number(repo):
    tag(repo, "v0.9.0")
    tag(repo, "v0.10.0")
    assert versions._last_tag(repo) == "v0.10.0"
    set_version(repo, "0.9.5")
    assert versions.guard(repo) == ["VERSION says 0.9.5, lower than the last release v0.10.0"]


def test_tags_that_are_not_release_versions_are_ignored(repo):
    for name in ["v0.1.0", "v1.0.0-rc1", "latest"]:
        tag(repo, name)
    assert versions._last_tag(repo) == "v0.1.0"
    assert versions.guard(repo) == []


def test_guard_reports_a_version_that_is_not_x_y_z(repo):
    (repo / "VERSION").write_text("dev\n")
    assert versions.guard(repo) == [_not_release("dev")]


def test_cli_guard(repo):
    result = run(repo, "guard")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    tag(repo, "v0.1.0")
    change(repo, "backend/app/main.py")
    result = run(repo, "guard")
    assert (result.returncode, result.stdout, result.stderr) == (1, "", product_changed("backend/app/main.py") + "\n")
