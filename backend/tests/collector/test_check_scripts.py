"""The check scripts, run on the fake server the way the collector runs them."""

from collections.abc import Sequence

from app.collector.checks import CHECKS
from app.collector.checks.parse import MAX_OUTPUT, ContainersResult, Outcome, read
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
