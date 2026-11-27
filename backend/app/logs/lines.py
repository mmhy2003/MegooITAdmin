"""Log lines: cutting a source's output into lines, and reading each line's time, level, unit and text.

A source's output is bytes in chunks of any size. The splitter gives whole lines and never holds more than its limit,
so a line without an end cannot fill the worker's memory: the part over the limit is dropped and the line is marked
as cut. A line's text is at most MAX_LINE_BYTES, decoded with replacement characters, and nothing in it is trusted:
a journal entry that is not JSON, or a container line without a valid time, is kept whole as plain text.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.logs.sources import PRIORITIES
from app.metrics.overview import iso

MAX_LINE_BYTES = 8192
MAX_JOURNAL_BYTES = 65536  # a journal entry is JSON: its MESSAGE is cut to MAX_LINE_BYTES after parsing
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DOCKER_TIME = re.compile(rb"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d) ")


@dataclass(frozen=True)
class Line:
    seq: int
    time: datetime
    text: str
    truncated: bool = False
    level: str | None = None  # journal: PRIORITIES[PRIORITY]
    unit: str | None = None  # journal: _SYSTEMD_UNIT


def line_message(line: Line) -> dict:
    """The line as the viewer gets it: level and unit only when known, truncated only when true."""
    message: dict = {"seq": line.seq, "time": iso(line.time), "text": line.text}
    if line.level is not None:
        message["level"] = line.level
    if line.unit is not None:
        message["unit"] = line.unit
    if line.truncated:
        message["truncated"] = True
    return message


class Splitter:
    """Complete lines out of chunks, each with whether it was cut at max_bytes."""

    def __init__(self, max_bytes: int):
        self._max = max_bytes
        self._buffer = bytearray()
        self._over = 0  # bytes of the current line dropped past max_bytes
        self._last = b""  # the last of them, so that a cut "\r" alone does not count as a cut

    def feed(self, chunk: bytes) -> list[tuple[bytes, bool]]:
        """The lines that chunk completes, without their b"\\n" and one trailing b"\\r"."""
        lines = []
        start = 0
        while (end := chunk.find(b"\n", start)) != -1:
            self._add(chunk[start:end])
            lines.append(self._finish())
            start = end + 1
        self._add(chunk[start:])
        return lines

    def rest(self) -> list[tuple[bytes, bool]]:
        """The unterminated last line, when there is one."""
        return [self._finish()] if self._buffer or self._over else []

    def _add(self, part: bytes) -> None:
        room = self._max - len(self._buffer)
        self._buffer += part[:room]
        if len(part) > room:
            self._over += len(part) - room
            self._last = part[-1:]

    def _finish(self) -> tuple[bytes, bool]:
        line = bytes(self._buffer)
        if not self._over and line.endswith(b"\r"):
            line = line[:-1]
        cut = self._over > 1 or (self._over == 1 and self._last != b"\r")
        self._buffer.clear()
        self._over = 0
        self._last = b""
        return line, cut


def _text(raw: bytes, cut: bool) -> tuple[str, bool]:
    return raw[:MAX_LINE_BYTES].decode(errors="replace"), cut or len(raw) > MAX_LINE_BYTES


def _plain(raw: bytes, seq: int, time: datetime, cut: bool) -> Line:
    text, truncated = _text(raw, cut)
    return Line(seq=seq, time=time, text=text, truncated=truncated)


def _docker_time(match: re.Match[bytes]) -> datetime | None:
    stamp, fraction, zone = (part.decode() if part else "" for part in match.groups())
    try:
        return datetime.fromisoformat(f"{stamp}.{fraction.ljust(6, '0')[:6]}{'+00:00' if zone == 'Z' else zone}")
    except ValueError:
        return None


def _journal_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return None
    try:
        return EPOCH + timedelta(microseconds=int(value))
    except OverflowError:
        return None


def _journal_message(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, list) and all(type(b) is int and 0 <= b <= 255 for b in value):
        return bytes(value)
    return b""


def parse(kind: str, raw: bytes, *, seq: int, read_at: datetime, cut: bool = False) -> Line:
    """The line of a source of that kind; read_at is its time when the line gives none."""
    if kind == "container" and (match := DOCKER_TIME.match(raw)) and (time := _docker_time(match)):
        return _plain(raw[match.end():], seq, time, cut)
    if kind != "journal":
        return _plain(raw, seq, read_at, cut)
    try:
        entry = json.loads(raw)
    except (ValueError, RecursionError):
        entry = None
    if not isinstance(entry, dict):
        return _plain(raw, seq, read_at, cut)
    text, truncated = _text(_journal_message(entry.get("MESSAGE")), cut)
    priority = entry.get("PRIORITY")
    unit = entry.get("_SYSTEMD_UNIT")
    return Line(
        seq=seq,
        time=_journal_time(entry.get("__REALTIME_TIMESTAMP")) or read_at,
        text=text,
        truncated=truncated,
        level=PRIORITIES[int(priority)] if priority in ("0", "1", "2", "3", "4", "5", "6", "7") else None,
        unit=unit if isinstance(unit, str) else None,
    )
