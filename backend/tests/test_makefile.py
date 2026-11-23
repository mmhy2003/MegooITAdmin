"""The Makefile's targets, run in a copy of the Makefile. Most use make -n, which prints the commands and runs
none of them. They need make, not Docker."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
UP = "up -d --build --wait --wait-timeout 300"
TARGETS = ["up", "down", "logs", "migrate", "shell-backend", "migration", "test", "test-security", "release-check"]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    if shutil.which("make") is None:
        pytest.fail("make is not on PATH. Install GNU Make to run these tests.")
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    versions = tmp_path / "backend" / "migrations" / "versions"
    versions.mkdir(parents=True)
    for name in ("0001_initial.py", "0007_add_servers.py"):
        (versions / name).write_text("")
    return tmp_path


def make(workdir: Path, *args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    # Without the caller's STACK, name or make flags (make test runs this suite from inside make).
    env = {k: v for k, v in os.environ.items() if k not in {"STACK", "name", "MAKEFLAGS", "MAKELEVEL", "MFLAGS"}}
    if path:
        env["PATH"] = path
    return subprocess.run(["make", "--no-print-directory", *args], cwd=workdir, env=env, capture_output=True, text=True, timeout=30)


def test_plain_make_lists_the_targets(workdir):
    result = make(workdir)
    assert result.returncode == 0, result.stderr
    for target in TARGETS:
        assert target in result.stdout


def test_up_creates_env_then_starts_the_real_instance_and_waits(workdir):
    result = make(workdir, "-n", "up")
    assert result.returncode == 0, result.stderr
    assert f"docker compose {UP}" in result.stdout.splitlines()
    assert result.stdout.index("/dev/urandom") < result.stdout.index(f"docker compose {UP}")
    assert not (workdir / ".env").exists()


@pytest.mark.parametrize("stack", ["dev", "e2e"])
def test_up_with_a_stack_uses_its_own_project_and_env_file_and_never_env(workdir, stack):
    result = make(workdir, "-n", "up", f"STACK={stack}")
    assert result.returncode == 0, result.stderr
    assert f"docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {UP}" in result.stdout.splitlines()
    assert "/dev/urandom" not in result.stdout
    assert not (workdir / ".env").exists()


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("logs", "logs -f"),
        ("migrate", "exec backend alembic upgrade head"),
        ("shell-backend", "exec backend bash"),
    ],
)
def test_the_stack_targets_act_on_the_chosen_stack(workdir, target, command):
    result = make(workdir, "-n", target, "STACK=dev")
    assert f"docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {command}" in result.stdout.splitlines()


def test_down_keeps_the_database_volume(workdir):
    result = make(workdir, "-n", "down")
    assert result.stdout.splitlines() == ["docker compose down"]


@pytest.mark.parametrize("stack", ["prod", "dev e2e"])
def test_an_unknown_stack_stops(workdir, stack):
    result = make(workdir, "-n", "down", f"STACK={stack}")
    assert result.returncode != 0
    assert "STACK must be dev or e2e" in result.stderr


def test_the_env_rule_writes_a_random_password_only_its_owner_can_read(workdir):
    first = make(workdir, ".env")
    assert first.returncode == 0, first.stderr
    assert "Created .env" in first.stdout
    env_file = workdir / ".env"
    assert re.fullmatch(r"POSTGRES_PASSWORD=[0-9a-f]{32}\n", env_file.read_text())
    assert env_file.stat().st_mode & 0o777 == 0o600
    content, mtime = env_file.read_text(), env_file.stat().st_mtime_ns
    second = make(workdir, ".env")
    assert second.returncode == 0, second.stderr
    assert "Created" not in second.stdout
    assert (env_file.read_text(), env_file.stat().st_mtime_ns) == (content, mtime)


def test_migration_takes_the_next_number_and_the_name_as_its_message(workdir):
    result = make(workdir, "-n", "migration", "name=add_users")
    assert result.returncode == 0, result.stderr
    assert "--rev-id 0008 " in result.stdout
    assert '-m "add users"' in result.stdout


@pytest.mark.parametrize("args", [[], ["name="], ["name=x;y"], ["name=1abc"], ["name=add-users"]])
def test_migration_without_a_valid_name_runs_nothing(workdir, args):
    bin_dir = workdir / "bin"
    bin_dir.mkdir()
    runner = bin_dir / "megoocolab-runner"
    runner.write_text('#!/bin/sh\ntouch "$(dirname "$0")/ran"\n')
    runner.chmod(0o755)
    result = make(workdir, "migration", *args, path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode != 0
    assert "make migration needs a name" in result.stderr
    assert not (bin_dir / "ran").exists()


def test_test_security_says_its_suites_are_not_in_the_repository_yet(workdir):
    result = make(workdir, "test-security")
    assert result.returncode != 0
    assert "the security suites are not in the repository yet" in result.stderr


def test_release_check_runs_the_version_check_then_the_release_plan(workdir):
    result = make(workdir, "-n", "release-check")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["python tools/release/versions.py check", "python tools/release/versions.py plan"]
