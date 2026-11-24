"""The fake sshd of the test set (tools/fake-server): real OpenSSH in a container, never a real server.

megoo-setup.sh prepares megoo (the platform's account) and megoo-nologs (not in adm), megoo-nosudo (without its sudo
rule) and megoo-wide (allowed everything by sudo). megoo-docker (in the docker group) and megoo-root (uid 0) are made
by the image. All six sign in with this run's platform key.
"""

import os
import subprocess
from dataclasses import dataclass

import pytest
from conftest import RUN_TESTS

from app.ssh import keys

SETUP = "/usr/local/lib/megoo-setup.sh"
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

    def host_key(self) -> str:
        """The Ed25519 host key sshd serves, as "ssh-ed25519 AAAA…" without a comment."""
        result = self.exec("cat", "/etc/ssh/ssh_host_ed25519_key.pub")
        assert result.returncode == 0, result.stderr
        return " ".join(result.stdout.split()[:2])

    def swap_host_key(self) -> None:
        """New host keys, served once this returns."""
        result = self.exec("swap-host-key")
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
