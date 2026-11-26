"""The fake sshd of the test set (tools/fake-server): real OpenSSH in a container, never a real server.

megoo-setup.sh prepares megoo (the platform's account) and megoo-nologs (not in adm), megoo-nosudo (without its sudo
rule) and megoo-wide (allowed everything by sudo). megoo-docker (in the docker group) and megoo-root (uid 0) are made
by the image. All six sign in with this run's platform key.
"""

import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from conftest import RUN_TESTS

from app.ssh import keys

SETUP = "/usr/local/lib/megoo-setup.sh"
CTL = "/usr/local/sbin/megoo-ctl"
# Where the stubs (docker, systemctl, journalctl, apt-get and dnf) log each call, one line per call: the name, then each
# argument in brackets.
LOG = "/var/log/fake-tools.log"
# The stubs' fixtures: <tool>_<first argument> or <tool> is what a call prints, <fixture>.exit its exit status.
FIXTURES = "/etc/fake-tools"
ACCOUNTS = ("megoo", "megoo-nologs", "megoo-nosudo", "megoo-wide", "megoo-docker", "megoo-root")


@dataclass(frozen=True)
class FakeServer:
    host: str
    port: int
    container: str

    def exec(self, *args: str, input: str | None = None, user: str | None = None) -> subprocess.CompletedProcess[str]:
        """Runs a command in the container, as root unless a user is given."""
        as_user = ["-u", user] if user else []
        return subprocess.run(
            ["docker", "exec", "-i", *as_user, self.container, *args],
            input=input,
            text=True,
            capture_output=True,
            timeout=60,
        )

    def authorize(self, addresses: str | None = None) -> None:
        """Prepares the accounts with this run's platform key, accepted from these addresses (default: loopback and the
        private ranges)."""
        result = self.exec("authorize-key", *([addresses] if addresses else []), input=keys.public_key() + "\n")
        assert result.returncode == 0, result.stdout + result.stderr

    def setup(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Runs megoo-setup.sh with these arguments, as root."""
        return self.exec("sh", SETUP, *args)

    def ctl(self, *args: str, user: str = "megoo") -> subprocess.CompletedProcess[str]:
        """Runs megoo-ctl with these arguments through sudo, as this account."""
        return self.exec("sudo", "-n", CTL, *args, user=user)

    def clear_tool_log(self) -> None:
        """Empties the log of the stub tools."""
        result = self.exec("truncate", "-s", "0", LOG)
        assert result.returncode == 0, result.stderr

    def tool_log(self) -> list[str]:
        """The calls the stub tools received since the log was last cleared."""
        result = self.exec("cat", LOG)
        assert result.returncode == 0, result.stderr
        return result.stdout.splitlines()

    @contextmanager
    def fixture(self, name: str, text: str, exit: int = 0) -> Iterator[None]:
        """Makes the stub fixture <name> print this text and exit with this status, and puts the old one back on
        leaving."""
        path = f"{FIXTURES}/{name}"
        kept = (path, f"{path}.exit")
        for file in kept:
            self._root("sh", "-c", 'if [ -e "$1" ]; then mv "$1" "$1.saved"; fi', "sh", file)
        try:
            self._root("sh", "-c", 'cat > "$1"', "sh", path, input=text)
            if exit != 0:
                self._root("sh", "-c", 'cat > "$1"', "sh", f"{path}.exit", input=f"{exit}\n")
            yield
        finally:
            for file in kept:
                self._root("sh", "-c", 'rm -f "$1"; if [ -e "$1.saved" ]; then mv "$1.saved" "$1"; fi', "sh", file)

    @contextmanager
    def hidden(self, *paths: str) -> Iterator[None]:
        """Moves these files out of the way, and back on leaving."""
        moved: list[str] = []
        try:
            for path in paths:
                self._root("mv", path, f"{path}.hidden")
                moved.append(path)
            yield
        finally:
            for path in moved:
                self._root("mv", f"{path}.hidden", path)

    def _root(self, *args: str, input: str | None = None) -> None:
        result = self.exec(*args, input=input)
        assert result.returncode == 0, result.stderr

    def host_key(self) -> str:
        """The Ed25519 host key sshd serves, as "ssh-ed25519 AAAA…" without a comment."""
        result = self.exec("cat", "/etc/ssh/ssh_host_ed25519_key.pub")
        assert result.returncode == 0, result.stderr
        return " ".join(result.stdout.split()[:2])

    def swap_host_key(self) -> None:
        """New host keys, served once this returns."""
        result = self.exec("swap-host-key")
        assert result.returncode == 0, result.stderr

    def restart(self) -> None:
        """Restarts the container, and returns once sshd serves its Ed25519 key again."""
        self._docker("restart")
        deadline = time.monotonic() + 30
        probe = "ssh-keyscan -T 2 -t ed25519 127.0.0.1 2>/dev/null | grep -q ssh-ed25519"
        while self.exec("sh", "-c", probe).returncode != 0:
            if time.monotonic() > deadline:
                pytest.fail(f"sshd of {self.container} did not answer within 30 s of a restart")
            time.sleep(0.5)

    def pause(self) -> None:
        """Freezes every process of the container: connections stay open but nothing answers."""
        self._docker("pause")

    def unpause(self) -> None:
        self._docker("unpause")

    def kill_sessions(self, user: str = "megoo") -> None:
        """Kills every process of this account, its SSH sessions included."""
        result = self.exec("pkill", "-KILL", "-u", user)
        assert result.returncode in (0, 1), result.stderr  # 1: no process matched

    def loops(self, user: str = "megoo") -> int:
        """How many collector loops (sh -s <interval>) this account runs."""
        return int(self.exec("pgrep", "-c", "-u", user, "-f", "^sh -s [0-9]+$").stdout.strip() or 0)

    def _docker(self, command: str) -> None:
        result = subprocess.run(["docker", command, self.container], text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr

    def sign_ins(self) -> int:
        """How many key sign-ins sshd accepted since the container started."""
        logs = subprocess.run(["docker", "logs", self.container], text=True, capture_output=True, timeout=60)
        assert logs.returncode == 0, logs.stderr
        return (logs.stdout + logs.stderr).count("Accepted publickey")


def start() -> FakeServer:
    """Finds the fake server of this run's test set and prepares its accounts with this run's platform key."""
    port = os.environ.get("SSH_PORT")
    project = os.environ.get("MEGOO_SERVICES_PROJECT")
    for name, value in (("SSH_PORT", port), ("MEGOO_SERVICES_PROJECT", project)):
        if not value:
            pytest.fail(f"{name} is not set. Run the suite as: {RUN_TESTS}")
    found = subprocess.run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=fake-server",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )
    container = found.stdout.strip()
    if found.returncode != 0 or not container:
        pytest.fail(
            f"The fake server of {project} is not running ({found.stderr.strip()}). Run the suite as: {RUN_TESTS}"
        )
    server = FakeServer(host="127.0.0.1", port=int(port), container=container)
    keys.ensure_key()
    server.authorize()
    return server
