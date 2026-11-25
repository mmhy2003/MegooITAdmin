"""The check scripts, run on the fake server the way the collector runs them."""

import time
from collections.abc import Sequence

from app.collector.checks import CHECKS
from app.collector.checks.parse import MAX_OUTPUT, ContainersResult, Outcome, ProcessesResult, ServicesResult, read
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
