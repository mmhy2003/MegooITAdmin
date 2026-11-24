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
TARGETS = ["up", "down", "logs", "migrate", "shell-backend", "migration", "test", "test-security", "release-check", "setup-code", "reset-mfa", "reset-password", "ssh-public-key", "fake-server-swap"]
STACK_FILES = "-f docker-compose.yml -f docker-compose.build.yml -f tools/fake-server/docker-compose.stack.yml"


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
    # Without the caller's STACK, name, email or make flags (make test runs this suite from inside make).
    env = {k: v for k, v in os.environ.items() if k not in {"STACK", "name", "email", "MAKEFLAGS", "MAKELEVEL", "MFLAGS"}}
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
    assert f"docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {STACK_FILES} {UP}" in result.stdout.splitlines()
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
    assert f"docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {STACK_FILES} {command}" in result.stdout.splitlines()


@pytest.mark.parametrize("stack", ["dev", "e2e"])
def test_up_with_a_stack_authorizes_its_key_in_the_fake_server(workdir, stack):
    result = make(workdir, "-n", "up", f"STACK={stack}")
    assert result.returncode == 0, result.stderr
    compose = f"docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {STACK_FILES}"
    pipe = f"{compose} exec -T backend python -m app.ssh.cli public-key | {compose} exec -T fake-server authorize-key"
    assert pipe in result.stdout.splitlines()
    assert result.stdout.index(UP) < result.stdout.index(pipe)


@pytest.mark.parametrize("target", ["up", "down"])
def test_the_real_instance_never_gets_a_fake_server(workdir, target):
    result = make(workdir, "-n", target)
    assert result.returncode == 0, result.stderr
    assert "fake-server" not in result.stdout


@pytest.mark.parametrize(
    ("args", "compose"),
    [
        ([], "docker compose"),
        (["STACK=dev"], f"docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {STACK_FILES}"),
    ],
)
def test_ssh_public_key_prints_the_key_of_the_chosen_stack(workdir, args, compose):
    result = make(workdir, "-n", "ssh-public-key", *args)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"{compose} exec -T backend python -m app.ssh.cli public-key"]


@pytest.mark.parametrize("stack", ["dev", "e2e"])
def test_fake_server_swap_swaps_in_the_chosen_stack(workdir, stack):
    result = make(workdir, "-n", "fake-server-swap", f"STACK={stack}")
    assert result.returncode == 0, result.stderr
    command = f"docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {STACK_FILES} exec -T fake-server swap-host-key"
    assert command in result.stdout.splitlines()


def test_fake_server_swap_without_a_stack_runs_nothing(workdir):
    bin_dir = workdir / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/bin/sh\ntouch "$(dirname "$0")/ran"\n')
    docker.chmod(0o755)
    result = make(workdir, "fake-server-swap", path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode != 0
    assert "needs STACK=dev or STACK=e2e" in result.stderr
    assert not (bin_dir / "ran").exists()


def test_down_keeps_the_database_volume(workdir):
    result = make(workdir, "-n", "down")
    assert result.stdout.splitlines() == ["docker compose down"]


@pytest.mark.parametrize("stack", ["prod", "dev e2e"])
def test_an_unknown_stack_stops(workdir, stack):
    result = make(workdir, "-n", "down", f"STACK={stack}")
    assert result.returncode != 0
    assert "STACK must be dev or e2e" in result.stderr


def assert_a_second_run_changes_nothing(workdir: Path) -> None:
    env_file = workdir / ".env"
    content, mtime = env_file.read_text(), env_file.stat().st_mtime_ns
    second = make(workdir, ".env")
    assert second.returncode == 0, second.stderr
    assert "Created" not in second.stdout
    assert "Added" not in second.stdout
    assert (env_file.read_text(), env_file.stat().st_mtime_ns) == (content, mtime)


KEY_LINE = r"AUTH_SECRET_KEY=[0-9a-f]{64}\n"


def test_the_env_rule_writes_two_random_passwords_and_a_key_only_its_owner_can_read(workdir):
    first = make(workdir, ".env")
    assert first.returncode == 0, first.stderr
    assert "Created .env" in first.stdout
    env_file = workdir / ".env"
    match = re.fullmatch(
        r"POSTGRES_PASSWORD=([0-9a-f]{32})\nPOSTGRES_API_PASSWORD=([0-9a-f]{32})\nAUTH_SECRET_KEY=([0-9a-f]{64})\n",
        env_file.read_text(),
    )
    assert match
    assert match.group(1) != match.group(2)
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert_a_second_run_changes_nothing(workdir)


def test_the_env_rule_adds_the_api_password_to_an_older_env(workdir):
    env_file = workdir / ".env"
    original = f"POSTGRES_PASSWORD={'a1' * 16}\nMEGOOITADMIN_HTTP_PORT=127.0.0.1:8080\n"
    env_file.write_text(original)
    env_file.chmod(0o600)
    result = make(workdir, ".env")
    assert result.returncode == 0, result.stderr
    assert "Added POSTGRES_API_PASSWORD" in result.stdout
    assert "Added AUTH_SECRET_KEY" in result.stdout
    content = env_file.read_text()
    assert content.startswith(original)
    assert re.fullmatch(r"POSTGRES_API_PASSWORD=[0-9a-f]{32}\n" + KEY_LINE, content[len(original) :])
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert_a_second_run_changes_nothing(workdir)


def test_the_env_rule_adds_only_the_key_to_an_env_with_both_passwords(workdir):
    env_file = workdir / ".env"
    original = "POSTGRES_PASSWORD=abc\nPOSTGRES_API_PASSWORD=def\n"
    env_file.write_text(original)
    env_file.chmod(0o600)
    result = make(workdir, ".env")
    assert result.returncode == 0, result.stderr
    assert "Added AUTH_SECRET_KEY" in result.stdout
    assert "Added POSTGRES_API_PASSWORD" not in result.stdout
    content = env_file.read_text()
    assert content.startswith(original)
    assert re.fullmatch(KEY_LINE, content[len(original) :])
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert_a_second_run_changes_nothing(workdir)


def test_the_env_rule_puts_the_added_line_on_a_line_of_its_own(workdir):
    env_file = workdir / ".env"
    env_file.write_text("POSTGRES_PASSWORD=abc")
    result = make(workdir, ".env")
    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"POSTGRES_PASSWORD=abc\nPOSTGRES_API_PASSWORD=[0-9a-f]{32}\n" + KEY_LINE, env_file.read_text())


def test_the_env_rule_leaves_a_complete_env_untouched(workdir):
    complete = f"POSTGRES_PASSWORD=abc\nPOSTGRES_API_PASSWORD=def\nAUTH_SECRET_KEY={'0f' * 32}\n"
    (workdir / ".env").write_text(complete)
    assert_a_second_run_changes_nothing(workdir)
    assert (workdir / ".env").read_text() == complete


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


def test_test_security_runs_the_security_suites(workdir):
    result = make(workdir, "-n", "test-security")
    assert result.returncode == 0, result.stderr
    assert "cd backend && megoocolab-runner services run test -- uv run pytest tests/security" in result.stdout.splitlines()


def test_setup_code_runs_the_command_in_the_chosen_stack(workdir):
    result = make(workdir, "-n", "setup-code", "STACK=dev")
    assert result.returncode == 0, result.stderr
    command = f"docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {STACK_FILES} exec backend python -m app.auth.cli setup-code"
    assert command in result.stdout.splitlines()


@pytest.mark.parametrize("target", ["reset-mfa", "reset-password"])
def test_the_reset_targets_run_their_command_in_the_chosen_stack(workdir, target):
    result = make(workdir, "-n", target, "email=a@b.c", "STACK=dev")
    assert result.returncode == 0, result.stderr
    command = f'docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {STACK_FILES} exec backend python -m app.auth.cli {target} "a@b.c"'
    assert command in result.stdout.splitlines()


@pytest.mark.parametrize("target", ["reset-mfa", "reset-password"])
@pytest.mark.parametrize("args", [[], ["email="], ["email=a;b"], ["email=a@b@c"]])
def test_a_reset_target_without_a_valid_email_runs_nothing(workdir, target, args):
    bin_dir = workdir / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/bin/sh\ntouch "$(dirname "$0")/ran"\n')
    docker.chmod(0o755)
    result = make(workdir, target, *args, path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode != 0
    assert f"make {target} needs an email" in result.stderr
    assert not (bin_dir / "ran").exists()


def test_release_check_runs_the_version_check_then_the_release_plan(workdir):
    result = make(workdir, "-n", "release-check")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["python tools/release/versions.py check", "python tools/release/versions.py plan"]
