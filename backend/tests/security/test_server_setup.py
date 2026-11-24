"""The task's sentence: the platform's account may use sudo only through megoo-ctl, and megoo-ctl passes on only the
calls in its table."""

import time

import pytest

SYSTEMCTL = "systemctl [--no-pager] [--no-ask-password]"

ALLOWED = [
    ("docker ps", "docker [ps] [--all] [--no-trunc] [--format] [{{json .}}]"),
    ("docker logs web-1", "docker [logs] [--timestamps] [web-1]"),
    (
        "docker logs web-1 --follow --tail 100 --since 10m",
        "docker [logs] [--timestamps] [--follow] [--tail] [100] [--since] [10m] [web-1]",
    ),
    (
        "docker logs 0123abcd --since 2026-11-24T10:00:00Z",
        "docker [logs] [--timestamps] [--since] [2026-11-24T10:00:00Z] [0123abcd]",
    ),
    ("docker start web-1", "docker [start] [web-1]"),
    ("docker stop web-1", "docker [stop] [web-1]"),
    ("docker restart web-1", "docker [restart] [web-1]"),
    ("systemctl restart nginx.service", f"{SYSTEMCTL} [restart] [--] [nginx.service]"),
    ("systemctl enable getty@tty1.service", f"{SYSTEMCTL} [enable] [--] [getty@tty1.service]"),
    ("systemctl stop docker.socket", f"{SYSTEMCTL} [stop] [--] [docker.socket]"),
    ("systemctl disable apt-daily.timer", f"{SYSTEMCTL} [disable] [--] [apt-daily.timer]"),
]

# Each call is a list of arguments, so "x.service;id" and "$(id)" reach megoo-ctl as they are, never through a shell.
REFUSED = [
    ["systemctl", "enable", "/home/megoo/x.service"],
    ["systemctl", "start", "reboot.target"],
    ["systemctl", "start", "a.service", "b.service"],
    ["systemctl", "daemon-reload"],
    ["systemctl", "start", "-x.service"],
    ["systemctl", "start", "x.service;id"],
    ["docker", "run", "alpine"],
    ["docker", "exec", "web-1", "sh"],
    ["docker", "ps", "--all"],
    ["docker", "logs", "--host=tcp://x"],
    ["docker", "logs", "-H"],
    ["docker", "logs", "web-1", "--tail", "ten"],
    ["docker", "logs", "web-1", "--since", "$(id)"],
    ["docker", "restart", "../x"],
    ["docker", "restart", "a", "b"],
    ["kill", "INT", "1234"],
    ["kill", "TERM", "1"],
    ["kill", "TERM", "0"],
    ["kill", "TERM", "-1"],
    ["kill", "TERM", "1;id"],
    ["kill", "TERM", "12", "1"],
    ["renice", "99", "1234"],
    ["renice", "-21", "1234"],
    ["renice", "5", "1"],
    ["version", "extra"],
    ["sh"],
    [],
]


def test_sudo_refuses_anything_but_megoo_ctl(fake_server):
    fake_server.clear_tool_log()
    for command in (["true"], ["/bin/sh", "-c", "id"], ["docker", "ps"]):
        result = fake_server.exec("sudo", "-n", *command, user="megoo")
        assert result.returncode != 0, command
    assert fake_server.tool_log() == []

    version = fake_server.ctl("version")
    assert version.returncode == 0, version.stderr
    assert version.stdout == "megoo-ctl 1\n"


def test_megoo_is_in_the_log_groups_and_not_in_docker(fake_server):
    groups = fake_server.exec("id", "-Gn", "megoo").stdout.split()
    assert {"systemd-journal", "adm"} <= set(groups)
    assert "docker" not in groups


@pytest.mark.parametrize(("args", "logged"), ALLOWED)
def test_an_allowed_call_reaches_the_tool_with_exactly_these_arguments(fake_server, args, logged):
    fake_server.clear_tool_log()

    result = fake_server.ctl(*args.split())

    assert result.returncode == 0, result.stderr
    assert fake_server.tool_log() == [logged]


@pytest.mark.parametrize("args", REFUSED, ids=lambda args: " ".join(args) or "no arguments")
def test_a_refused_call_reaches_no_tool(fake_server, args):
    fake_server.clear_tool_log()

    result = fake_server.ctl(*args)

    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.startswith("megoo-ctl: refused"), result.stderr
    assert fake_server.tool_log() == []


def test_kill_and_renice_act_on_a_real_process(fake_server):
    started = fake_server.exec("sh", "-c", "setsid sleep 300 > /dev/null 2>&1 < /dev/null & echo $!")
    assert started.returncode == 0, started.stderr
    pid = started.stdout.strip()

    def ps(field: str) -> str:
        return fake_server.exec("ps", "-o", f"{field}=", "-p", pid).stdout.strip()

    try:
        assert fake_server.ctl("renice", "5", pid).returncode == 0
        assert ps("ni") == "5"

        assert fake_server.ctl("kill", "STOP", pid).returncode == 0
        assert ps("stat").startswith("T")
        assert fake_server.ctl("kill", "CONT", pid).returncode == 0
        assert not ps("stat").startswith("T")

        assert fake_server.ctl("kill", "TERM", pid).returncode == 0
        deadline = time.monotonic() + 5
        while (stat := ps("stat")) and not stat.startswith("Z") and time.monotonic() < deadline:
            time.sleep(0.1)
        assert stat == "" or stat.startswith("Z"), stat
    finally:
        fake_server.exec("kill", "-KILL", pid)
