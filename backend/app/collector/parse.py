"""The loop's output: a byte stream cut into lines, and each line read as one sample (script.sh prints the format).

The server's account writes this output, so every size is bounded: a line, a name and the number of rows of each list.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

MAX_LINE = 256 * 1024
MAX_NAME = 255
MAX_CORES = 256  # cpu rows kept: the whole-server row and 256 cores
MAX_DEVICES = 64  # interfaces, disks and filesystems kept, each

_KEEP = {"cpu": MAX_CORES + 1, "net": MAX_DEVICES, "disk": MAX_DEVICES, "fs": MAX_DEVICES}


class Lines:
    """Cuts a byte stream into lines. A line longer than max_line is skipped up to its newline and counted."""

    def __init__(self, max_line: int = MAX_LINE) -> None:
        self.max_line = max_line
        self.too_long = 0
        self._tail = b""
        self._skipping = False

    def feed(self, chunk: bytes) -> list[bytes]:
        """The lines that chunk completes, without b"\\n". The unfinished tail waits for the next chunk."""
        if self._skipping:
            end = chunk.find(b"\n")
            if end < 0:
                return []
            chunk = chunk[end + 1 :]
            self._skipping = False
        *complete, tail = (self._tail + chunk).split(b"\n")
        lines = []
        for line in complete:
            if len(line) > self.max_line:
                self.too_long += 1
            else:
                lines.append(line)
        if len(tail) > self.max_line:
            self.too_long += 1
            tail = b""
            self._skipping = True
        self._tail = tail
        return lines


Counter = NonNegativeInt
Load = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Memory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    total: Counter
    available: Counter
    swap_total: Counter
    swap_free: Counter


class Raw(BaseModel):
    """One sample as the loop prints it: counters since boot, before any rate is computed."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    v: Literal[1]
    uptime: float = Field(ge=0, allow_inf_nan=False)
    load: tuple[Load, Load, Load]
    # name, then user, nice, system, idle, iowait, irq, softirq and steal
    cpu: tuple[tuple[str, Counter, Counter, Counter, Counter, Counter, Counter, Counter, Counter], ...]
    mem: Memory
    # name, rx and tx bytes
    net: tuple[tuple[str, Counter, Counter], ...]
    # name, sectors read, sectors written and ms doing I/O
    disk: tuple[tuple[str, Counter, Counter, Counter], ...]
    # mount point, size, used and available in kB, inodes and used inodes
    fs: tuple[tuple[str, Counter, Counter, Counter, Counter, Counter], ...]

    @model_validator(mode="before")
    @classmethod
    def _bound(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key, keep in _KEEP.items():
            rows = data.get(key)
            if isinstance(rows, list):
                data[key] = [row for row in rows if not _long_name(row)][:keep]
        return data


def _long_name(row: Any) -> bool:
    return isinstance(row, list) and bool(row) and isinstance(row[0], str) and len(row[0]) > MAX_NAME


def parse(line: bytes) -> Raw:
    """The sample on line. ValueError (pydantic's ValidationError is one) for anything that is not a sample."""
    return Raw.model_validate_json(line)
