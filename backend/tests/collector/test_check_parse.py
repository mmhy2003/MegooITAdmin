import logging

import pytest

from app.collector.checks.parse import MAX_LINE, CheckResult, NotAvailable, Outcome, clean, read
from app.ssh.client import ScriptResult

OK = b'{"status":"ok"}\n'


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
    from datetime import UTC, datetime

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
