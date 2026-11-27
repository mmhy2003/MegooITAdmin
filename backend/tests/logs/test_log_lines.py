import json
from datetime import UTC, datetime

from app.logs.lines import MAX_LINE_BYTES, Line, Splitter, line_message, parse

READ_AT = datetime(2026, 11, 27, 12, 0, 0, tzinfo=UTC)


def test_the_splitter_keeps_lines_across_chunks():
    splitter = Splitter(100)

    assert splitter.feed(b"a\nb") == [(b"a", False)]
    assert splitter.feed(b"c\n") == [(b"bc", False)]
    assert splitter.rest() == []


def test_a_crlf_ending_loses_its_cr():
    splitter = Splitter(100)

    assert splitter.feed(b"one\r\ntwo\r") == [(b"one", False)]
    assert splitter.feed(b"\n") == [(b"two", False)]
    assert Splitter(3).feed(b"abc\r\n") == [(b"abc", False)]


def test_a_long_line_is_cut_and_its_rest_discarded():
    splitter = Splitter(10)

    out = splitter.feed(b"0123456") + splitter.feed(b"789abcdefg") + splitter.feed(b"hijklmno")
    assert out == []
    assert splitter.feed(b"\nnext\n") == [(b"0123456789", True), (b"next", False)]


def test_rest_gives_the_unterminated_line():
    splitter = Splitter(100)

    assert splitter.feed(b"done\nhalf") == [(b"done", False)]
    assert splitter.rest() == [(b"half", False)]
    assert splitter.rest() == []


def test_a_journal_entry_gives_time_level_unit_and_text():
    raw = json.dumps({
        "__REALTIME_TIMESTAMP": "1795780800123456", "PRIORITY": "3", "_SYSTEMD_UNIT": "nginx.service",
        "MESSAGE": "upstream timed out",
    }).encode()

    line = parse("journal", raw, seq=4, read_at=READ_AT)

    assert line == Line(seq=4, time=datetime(2026, 11, 27, 12, 0, 0, 123456, tzinfo=UTC), text="upstream timed out",
                        level="err", unit="nginx.service")


def test_a_binary_journal_message_becomes_text():
    raw = json.dumps({"MESSAGE": [104, 105, 255], "__REALTIME_TIMESTAMP": "1795780800000000"}).encode()

    assert parse("journal", raw, seq=1, read_at=READ_AT).text == "hi�"


def test_a_journal_entry_without_a_valid_time_uses_the_read_time():
    for stamp in (None, "soon", "-5", 12):
        entry = {"MESSAGE": "x"} if stamp is None else {"MESSAGE": "x", "__REALTIME_TIMESTAMP": stamp}
        line = parse("journal", json.dumps(entry).encode(), seq=1, read_at=READ_AT)

        assert line.time == READ_AT
        assert line.level is None and line.unit is None


def test_a_journal_line_that_is_not_json_is_kept_as_text():
    for raw in (b"-- No entries --", b"[1, 2]"):
        line = parse("journal", raw, seq=2, read_at=READ_AT)

        assert line == Line(seq=2, time=READ_AT, text=raw.decode())


def test_a_docker_timestamp_with_nanoseconds_gives_the_time():
    line = parse("container", b"2026-11-27T10:00:00.123456789Z hello", seq=1, read_at=READ_AT)

    assert line.time == datetime(2026, 11, 27, 10, 0, 0, 123456, tzinfo=UTC)
    assert line.text == "hello"


def test_a_bad_docker_timestamp_keeps_the_whole_line_and_the_read_time():
    for raw in (b"2026-13-45T10:00:00Z hello", b"no time here"):
        line = parse("container", raw, seq=1, read_at=READ_AT)

        assert line.time == READ_AT
        assert line.text == raw.decode()


def test_bad_utf8_is_replaced():
    line = parse("file", b"caf\xc3 ok", seq=1, read_at=READ_AT)

    assert line.text == "caf� ok"
    assert line.time == READ_AT


def test_a_text_over_8_kb_is_cut_and_marked():
    line = parse("file", b"x" * (MAX_LINE_BYTES + 5), seq=1, read_at=READ_AT)
    assert line.text == "x" * MAX_LINE_BYTES and line.truncated

    message = json.dumps({"MESSAGE": "y" * (MAX_LINE_BYTES + 1)}).encode()
    assert parse("journal", message, seq=1, read_at=READ_AT).truncated
    assert parse("file", b"short", seq=1, read_at=READ_AT, cut=True).truncated
    assert not parse("file", b"short", seq=1, read_at=READ_AT).truncated


def test_line_message_omits_empty_fields():
    assert line_message(parse("file", b"plain", seq=7, read_at=READ_AT)) == {
        "seq": 7, "time": "2026-11-27T12:00:00Z", "text": "plain",
    }
    full = Line(seq=8, time=READ_AT, text="t", truncated=True, level="warning", unit="a.service")
    assert line_message(full) == {
        "seq": 8, "time": "2026-11-27T12:00:00Z", "text": "t", "level": "warning", "unit": "a.service",
        "truncated": True,
    }
