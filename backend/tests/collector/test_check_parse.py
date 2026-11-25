import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.checks.models import SeenContainer
from app.collector.checks import parse
from app.collector.checks.parse import MAX_LINE, CheckResult, NotAvailable, Outcome, clean, read
from app.metrics.samples import Reading
from app.ssh.client import ScriptResult

OK = b'{"status":"ok"}\n'
FIXTURES = Path(__file__).resolve().parents[3] / "tools" / "fake-server" / "fixtures"
DOCKER_PS = (FIXTURES / "docker_ps").read_bytes().splitlines()


class Echo(CheckResult):
    lines: list[str]


def echo(lines: list[bytes]) -> Echo:
    return Echo(lines=[line.decode() for line in lines])


def _done(output: bytes, exit_status: int | None = 0, truncated: bool = False) -> ScriptResult:
    return ScriptResult(exit_status=exit_status, output=output, truncated=truncated)


def test_ok_gives_the_parsed_body() -> None:
    outcome = read(echo, _done(OK + b"one\ntwo\n"))

    assert outcome == Outcome("ok", Echo(lines=["one", "two"]))


def test_ok_without_a_trailing_newline_keeps_the_last_line() -> None:
    assert read(echo, _done(OK + b"one\ntwo")) == Outcome("ok", Echo(lines=["one", "two"]))


def test_ok_with_no_body_gives_no_lines() -> None:
    assert read(echo, _done(OK)) == Outcome("ok", Echo(lines=[]))


@pytest.mark.parametrize("status", ["not_available", "denied"])
def test_not_available_and_denied_do_not_call_the_parser(status: str) -> None:
    def parser(lines: list[bytes]) -> CheckResult:
        raise AssertionError("the parser was called")

    outcome = read(parser, _done(f'{{"status":"{status}"}}\n'.encode()))

    assert outcome == Outcome(status)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "result",
    [
        _done(OK + b"one\n", exit_status=1),
        _done(OK + b"one\n", exit_status=None),
        _done(OK + b"one\n", truncated=True),
        _done(b""),
        _done(b'{"status":"maybe"}\n'),
        _done(b"not json\n"),
        _done(b'{"status":"ok","extra":1}\n'),
        _done(b'["ok"]\n'),
        _done(b'{"status":"timeout"}\n'),
        _done(b"\xff\xfe\n"),
    ],
    ids=["exit-1", "no-exit", "truncated", "empty", "maybe", "not-json", "extra-key", "list", "timeout", "bad-utf8"],
)
def test_a_bad_output_fails(result: ScriptResult) -> None:
    assert read(echo, result) == Outcome("failed")


def test_a_body_line_longer_than_max_line_fails() -> None:
    assert read(echo, _done(OK + b"x" * (MAX_LINE + 1) + b"\n")) == Outcome("failed")


def test_a_body_line_of_max_line_is_read() -> None:
    outcome = read(echo, _done(OK + b"x" * MAX_LINE + b"\n"))

    assert outcome.status == "ok"


def test_the_parser_raising_not_available_gives_not_available() -> None:
    def parser(lines: list[bytes]) -> CheckResult:
        raise NotAvailable

    assert read(parser, _done(OK + b"one\n")) == Outcome("not_available")


def test_the_parser_raising_value_error_fails() -> None:
    def parser(lines: list[bytes]) -> CheckResult:
        raise ValueError("bad")

    assert read(parser, _done(OK + b"one\n")) == Outcome("failed")


def test_a_validation_error_fails() -> None:
    def parser(lines: list[bytes]) -> CheckResult:
        return Echo(lines=1)  # type: ignore[arg-type]

    assert read(parser, _done(OK + b"one\n")) == Outcome("failed")


def test_a_result_is_frozen_and_refuses_unknown_fields() -> None:
    result = Echo(lines=["a"])

    with pytest.raises(ValueError):
        Echo(lines=["a"], other=1)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        result.lines = []  # type: ignore[misc]


def test_a_result_gives_its_data_and_no_readings() -> None:
    result = Echo(lines=["a"])

    assert result.data() == {"lines": ["a"]}
    assert result.readings(datetime.now(UTC)) == ()


def test_clean() -> None:
    assert clean("a" * 256) is None
    assert clean("a" * 255) == "a" * 255
    assert clean("bad\x00") is None
    assert clean("tab\there") is None
    assert clean("nginx") == "nginx"


def test_nothing_from_the_output_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    def parser(lines: list[bytes]) -> CheckResult:
        raise ValueError(lines[0].decode())

    caplog.set_level(logging.DEBUG)

    read(parser, _done(OK + b"secret-text\n"))
    read(echo, _done(b"secret-text\n"))
    read(echo, _done(OK + b"secret-text\n", exit_status=1))

    assert "secret-text" not in caplog.text


def _container(**fields: str) -> bytes:
    row = {"ID": "a" * 64, "Names": "one", "Image": "busybox", "Labels": "", "State": "running", "Status": "Up"}
    return json.dumps(row | fields).encode()


def test_containers_reads_the_fixture() -> None:
    result = parse.containers(DOCKER_PS)

    assert result.containers == (
        SeenContainer("1" * 64, "shop-web-1", "nginx:1.27", "shop", "web", "running", "Up 3 days (healthy)"),
        SeenContainer("2" * 64, "shop-db-1", "postgres:17", "shop", "db", "running", "Up 3 days"),
        SeenContainer(
            "3" * 64,
            "monitoring-grafana-1",
            "grafana/grafana:11.3.0",
            "monitoring",
            "grafana",
            "exited",
            "Exited (0) 2 hours ago",
        ),
        SeenContainer("4" * 64, "hello-adhoc", "busybox:1.37", None, None, "restarting", "Restarting (1) 5 seconds ago"),
    )
    assert (result.total, result.running, result.not_running) == (4, 2, 2)


def test_containers_data_leaves_the_list_out() -> None:
    assert parse.containers(DOCKER_PS).data() == {"total": 4, "running": 2, "not_running": 2}


def test_containers_readings() -> None:
    assert parse.containers(DOCKER_PS).readings(datetime.now(UTC)) == (
        Reading(metric="containers.running", value=2),
        Reading(metric="containers.not_running", value=2),
    )


def test_containers_an_unknown_state_is_unknown_and_not_running() -> None:
    result = parse.containers([_container(State="weird")])

    assert result.containers[0].state == "unknown"
    assert (result.total, result.running, result.not_running) == (1, 0, 1)


def test_containers_a_state_is_lowered() -> None:
    assert parse.containers([_container(State="Paused")]).containers[0].state == "paused"


def test_containers_a_project_label_in_the_middle_is_found() -> None:
    labels = "a=b,com.docker.compose.service=api,com.docker.compose.project=shop,c=d"

    seen = parse.containers([_container(Labels=labels)]).containers[0]

    assert (seen.compose_project, seen.compose_service) == ("shop", "api")


def test_containers_a_bad_project_label_is_no_project() -> None:
    seen = parse.containers([_container(Labels="com.docker.compose.project=a b")]).containers[0]

    assert seen.compose_project is None


def test_containers_the_first_name_is_kept() -> None:
    assert parse.containers([_container(Names="one,two")]).containers[0].name == "one"


@pytest.mark.parametrize(
    "fields",
    [
        {"Names": "bad\x01name"},
        {"Image": "bad\x01image"},
        {"Image": "x" * 256},
        {"ID": "not-an-id"},
        {"ID": "a" * 11},
        {"ID": "A" * 64},
    ],
    ids=["control-in-name", "control-in-image", "long-image", "bad-id", "short-id", "upper-id"],
)
def test_containers_a_bad_container_is_dropped_but_counted(fields: dict[str, str]) -> None:
    result = parse.containers([_container(**fields), _container(ID="b" * 12, State="exited")])

    assert [seen.container_id for seen in result.containers] == ["b" * 12]
    assert (result.total, result.running, result.not_running) == (2, 1, 1)


def test_containers_a_bad_status_is_empty() -> None:
    assert parse.containers([_container(Status="bad\x01")]).containers[0].status == ""


def test_containers_an_object_without_a_string_state_is_not_counted() -> None:
    result = parse.containers([_container(State=1), _container()])  # type: ignore[arg-type]

    assert (result.total, result.running, result.not_running) == (1, 1, 0)


def test_containers_keeps_500_and_counts_every_one() -> None:
    lines = [_container(ID=f"{i:064x}") for i in range(501)]

    result = parse.containers(lines)

    assert len(result.containers) == 500
    assert (result.total, result.running, result.not_running) == (501, 501, 0)


def test_containers_with_none_is_empty() -> None:
    result = parse.containers([])

    assert result.containers == ()
    assert (result.total, result.running, result.not_running) == (0, 0, 0)


@pytest.mark.parametrize("line", [b"not json", b'["a"]', b"1", b"\xff"], ids=["not-json", "list", "number", "bad-utf8"])
def test_containers_a_line_that_is_not_an_object_fails(line: bytes) -> None:
    with pytest.raises(ValueError):
        parse.containers([_container(), line])


def test_containers_through_read() -> None:
    outcome = read(parse.containers, _done(OK + b"\n".join(DOCKER_PS) + b"\n"))

    assert outcome.status == "ok"
    assert isinstance(outcome.result, parse.ContainersResult)
    assert outcome.result.running == 2
