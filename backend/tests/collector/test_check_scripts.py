"""The check scripts, run on the fake server the way the collector runs them."""

import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.collector.checks import CHECKS
from app.collector.checks.parse import (
    MAX_OUTPUT,
    CertificatesResult,
    ContainersResult,
    LoginsResult,
    Outcome,
    ProcessesResult,
    ServicesResult,
    Source,
    UpdatesResult,
    read,
)
from app.ssh.client import connect, run_script


async def run(fake_server, kind: str, user: str = "megoo", args: Sequence[str] = ()) -> Outcome:
    """Runs the check of this kind as this account, and reads its output."""
    check = next(check for check in CHECKS if check.kind == kind)
    async with connect(fake_server.host, fake_server.port, user, fake_server.host_key()) as conn:
        result = await run_script(conn, check.script, args, timeout=check.timeout, max_output=MAX_OUTPUT)
    return read(check.parse, result)


def leftovers(fake_server, user: str = "megoo") -> list[str]:
    """The processes this account still runs, sshd's own left out. Taken after the connection closed."""
    names = fake_server.exec("ps", "-u", user, "-o", "comm=").stdout.split()
    return [name for name in names if not name.startswith("sshd")]


async def test_containers_lists_the_fixture(fake_server):
    fake_server.clear_tool_log()

    outcome = await run(fake_server, "containers")

    assert outcome.status == "ok"
    assert isinstance(outcome.result, ContainersResult)
    assert [seen.name for seen in outcome.result.containers] == [
        "shop-web-1",
        "shop-db-1",
        "monitoring-grafana-1",
        "hello-adhoc",
    ]
    assert fake_server.tool_log() == ["docker [ps] [--all] [--no-trunc] [--format] [{{json .}}]"]
    assert leftovers(fake_server) == []


async def test_containers_is_denied_without_the_sudo_rule(fake_server):
    assert await run(fake_server, "containers", user="megoo-nosudo") == Outcome("denied")


async def test_containers_without_docker(fake_server):
    with fake_server.hidden("/usr/local/bin/docker"):
        assert await run(fake_server, "containers") == Outcome("not_available")


def new_files(fake_server) -> set[str]:
    found = fake_server.exec("find", "/", "-xdev", "-newer", "/tmp/marker", "-type", "f").stdout.split("\n")
    return {path for path in found if path.startswith(("/home/megoo/", "/tmp/")) and path != "/tmp/marker"}


def child_of(fake_server, pid: str) -> str:
    """The pid of this process's child, once it has started."""
    for _ in range(50):
        child = fake_server.exec("pgrep", "-P", pid).stdout.strip()
        if child.isdigit():
            return child
        time.sleep(0.1)
    raise AssertionError(f"{pid} has no child")


async def test_processes_puts_a_busy_loop_on_top(fake_server):
    started = fake_server.exec("sh", "-c", "timeout 20 sh -c 'while :; do :; done' > /dev/null 2>&1 & echo $!")
    timeout_pid = started.stdout.strip()
    try:
        loop_pid = child_of(fake_server, timeout_pid)

        outcome = await run(fake_server, "processes")

        assert outcome.status == "ok"
        assert isinstance(outcome.result, ProcessesResult)
        top = outcome.result.by_cpu[0]
        assert top.pid == int(loop_pid)
        assert top.cpu_percent > 50
    finally:
        fake_server.exec("pkill", "-P", timeout_pid)
        fake_server.exec("kill", timeout_pid)


async def test_processes_leaves_nothing_behind(fake_server):
    assert (await run(fake_server, "processes")).status == "ok"

    assert leftovers(fake_server) == []


async def test_processes_writes_no_file(fake_server):
    assert fake_server.exec("touch", "/tmp/marker").returncode == 0
    before = new_files(fake_server)

    assert (await run(fake_server, "processes")).status == "ok"

    assert new_files(fake_server) == before


async def test_services_reads_the_fixture(fake_server):
    fake_server.clear_tool_log()

    outcome = await run(fake_server, "services")

    assert outcome.status == "ok"
    assert isinstance(outcome.result, ServicesResult)
    assert outcome.result.failed == 1
    assert fake_server.tool_log() == [
        "systemctl [list-units] [--type=service] [--all] [--plain] [--no-legend] [--no-pager]"
    ]


async def test_services_without_systemctl(fake_server):
    with fake_server.hidden("/usr/local/bin/systemctl"):
        assert await run(fake_server, "services") == Outcome("not_available")


async def test_services_failing_tool_is_failed(fake_server):
    with fake_server.fixture("systemctl_list-units", "", exit=1):
        assert await run(fake_server, "services") == Outcome("failed")


JOURNAL = """\
Failed password for root from 203.0.113.9 port 50022 ssh2
Failed password for root from 203.0.113.9 port 50023 ssh2
Invalid user admin from 198.51.100.7 port 41000
Failed password for invalid user admin from 198.51.100.7 port 41000 ssh2
Invalid user x from 192.0.2.1 from 203.0.113.250 port 1
Accepted publickey for megoo from 10.0.0.5 port 2222 ssh2
"""


async def test_logins_counts_failed_passwords_and_unknown_accounts(fake_server):
    fake_server.clear_tool_log()

    with fake_server.fixture("journalctl", JOURNAL):
        outcome = await run(fake_server, "logins")

    assert outcome.status == "ok"
    assert isinstance(outcome.result, LoginsResult)
    # The failed password of an unknown account was counted once already, as "Invalid user".
    assert outcome.result.failed_24h == 4
    # The address is the one after the last " from ": the earlier one is part of the name the attacker chose.
    assert sorted(outcome.result.top_sources, key=lambda source: source.address) == [
        Source(address="198.51.100.7", count=1),
        Source(address="203.0.113.250", count=1),
        Source(address="203.0.113.9", count=2),
    ]
    assert outcome.result.top_sources[0] == Source(address="203.0.113.9", count=2)
    assert fake_server.tool_log() == [
        "journalctl [-q] [--no-pager] [-o] [cat] [--since=-24h] [-t] [sshd] [-t] [sshd-session]"
    ]


async def test_logins_without_a_journal(fake_server):
    with fake_server.hidden("/usr/local/bin/journalctl"):
        assert await run(fake_server, "logins") == Outcome("not_available")


async def test_logins_with_an_empty_journal(fake_server):
    assert await run(fake_server, "logins") == Outcome("ok", LoginsResult(failed_24h=0, top_sources=()))


APT_UPGRADE = """\
Inst openssl [3.5.1-1] (3.5.4-1 Debian-Security:13/stable-security [amd64])
Inst tzdata [2025a-1] (2025b-0+deb13u1 Debian:13.2/stable [all])
Conf openssl (3.5.4-1 Debian-Security:13/stable-security [amd64])
"""
APT_GET = ("/usr/local/bin/apt-get", "/usr/bin/apt-get")
DNF_CHECK_UPDATE = "openssl.x86_64  1:3.2.2-6.el9  baseos\ncurl.x86_64  7.76.1-31.el9  baseos\n"
DNF_UPDATEINFO = "RHSA-2025:1234 Important/Sec. openssl-1:3.2.2-6.el9.x86_64\n"


async def test_updates_with_apt(fake_server):
    fake_server.clear_tool_log()

    with fake_server.fixture("apt-get", APT_UPGRADE):
        outcome = await run(fake_server, "updates")
        assert fake_server.exec("touch", "/var/run/reboot-required").returncode == 0
        try:
            rebooting = await run(fake_server, "updates")
        finally:
            fake_server.exec("rm", "-f", "/var/run/reboot-required")

    assert outcome.status == "ok"
    assert isinstance(outcome.result, UpdatesResult)
    assert (outcome.result.manager, outcome.result.pending, outcome.result.security) == ("apt", 2, 1)
    assert outcome.result.reboot_required is False
    assert outcome.result.lists_refreshed_at is not None
    assert isinstance(rebooting.result, UpdatesResult)
    assert rebooting.result.reboot_required is True
    assert fake_server.tool_log()[0] == "apt-get [-s] [-o] [Debug::NoLocking=1] [upgrade]"


async def test_updates_with_dnf(fake_server):
    fake_server.clear_tool_log()

    with (
        fake_server.hidden(*APT_GET),
        fake_server.fixture("dnf_check-update", DNF_CHECK_UPDATE, exit=100),
        fake_server.fixture("dnf_updateinfo", DNF_UPDATEINFO),
    ):
        outcome = await run(fake_server, "updates")

    assert outcome.status == "ok"
    assert isinstance(outcome.result, UpdatesResult)
    assert (outcome.result.manager, outcome.result.pending, outcome.result.security) == ("dnf", 2, 1)
    assert outcome.result.reboot_required is None
    assert fake_server.tool_log()[0] == "dnf [check-update] [-C] [-q]"


async def test_updates_with_dnf_without_a_cache(fake_server):
    with (
        fake_server.hidden(*APT_GET),
        fake_server.fixture("dnf_check-update", "", exit=1),
        fake_server.fixture("dnf_updateinfo", DNF_UPDATEINFO),
    ):
        assert await run(fake_server, "updates") == Outcome("not_available")


async def test_updates_without_a_package_manager(fake_server):
    with fake_server.hidden(*APT_GET, "/usr/local/bin/dnf"):
        assert await run(fake_server, "updates") == Outcome("not_available")


def answers(fake_server, port: int) -> bool:
    """Whether something listens on this port of the fake server, waiting up to 5 seconds."""
    for _ in range(50):
        if fake_server.exec("bash", "-c", f"exec 3<> /dev/tcp/127.0.0.1/{port}").returncode == 0:
            return True
        time.sleep(0.1)
    return False


async def test_certificates_finds_a_served_certificate(fake_server):
    made = fake_server.exec(
        "sh",
        "-c",
        "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj /CN=fake-server -days 10"
        " -keyout /tmp/test-key.pem -out /tmp/test-cert.pem",
    )
    assert made.returncode == 0, made.stderr
    started = fake_server.exec(
        "sh",
        "-c",
        "openssl s_server -accept 8443 -cert /tmp/test-cert.pem -key /tmp/test-key.pem -quiet"
        " < /dev/null > /dev/null 2>&1 & echo $!",
    )
    server_pid = started.stdout.strip()
    try:
        assert answers(fake_server, 8443)

        outcome = await run(fake_server, "certificates", args=("fake-server",))

        assert outcome.status == "ok"
        assert isinstance(outcome.result, CertificatesResult)
        (cert,) = outcome.result.certificates
        assert (cert.port, cert.subject) == (8443, "CN=fake-server")
        assert timedelta(days=9) < cert.not_after - datetime.now(UTC) <= timedelta(days=10)
    finally:
        fake_server.exec("kill", server_pid)
        fake_server.exec("rm", "-f", "/tmp/test-key.pem", "/tmp/test-cert.pem")


async def test_certificates_with_nothing_served(fake_server):
    assert await run(fake_server, "certificates") == Outcome("ok", CertificatesResult(certificates=()))


async def test_certificates_without_openssl(fake_server):
    with fake_server.hidden("/usr/bin/openssl"):
        assert await run(fake_server, "certificates") == Outcome("not_available")


async def test_certificates_leaves_nothing_behind(fake_server):
    assert (await run(fake_server, "certificates")).status == "ok"

    assert leftovers(fake_server) == []
