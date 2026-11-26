"""The readings of one sample: load, memory and filesystems as they are, and rates from the counters of two samples.

Rates need the previous sample of the same boot. They are left out when there is none, when the uptime did not grow
(a reboot) and when a counter went down (a counter reset), rather than reported wrong.
"""

import re
from collections.abc import Iterable, Sequence

from app.collector.parse import Raw
from app.metrics.samples import Reading

WHOLE_DISK = re.compile(r"(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)")
SECTOR = 512
KIB = 1024


def counted_interface(name: str) -> bool:
    """Interfaces whose traffic is the server's: not the loopback, not a container's end of a veth pair."""
    return name != "lo" and not name.startswith("veth")


def whole_disk(name: str) -> bool:
    return WHOLE_DISK.fullmatch(name) is not None


def cores(raw: Raw) -> int:
    """The server's CPU cores: its cpuN rows, without the "cpu" total. At least 1."""
    return max(1, sum(1 for row in raw.cpu if row[0] != "cpu"))


def readings(previous: Raw | None, current: Raw) -> tuple[Reading, ...]:
    found = [*_levels(current)]
    if previous is not None and _comparable(previous, current):
        found += _rates(previous, current, current.uptime - previous.uptime)
    return tuple(found)


def _levels(raw: Raw) -> Iterable[Reading]:
    for name, value in zip(("load.1m", "load.5m", "load.15m"), raw.load, strict=True):
        yield Reading(metric=name, value=value)

    mem = raw.mem
    yield Reading(metric="mem.total_bytes", value=mem.total * KIB)
    if mem.available > 0:
        used = max(mem.total - mem.available, 0)
        yield Reading(metric="mem.available_bytes", value=mem.available * KIB)
        yield Reading(metric="mem.used_bytes", value=used * KIB)
        if mem.total > 0:
            yield Reading(metric="mem.used_percent", value=used / mem.total * 100)
    yield Reading(metric="swap.total_bytes", value=mem.swap_total * KIB)
    yield Reading(metric="swap.used_bytes", value=max(mem.swap_total - mem.swap_free, 0) * KIB)

    for mount, size, used, avail, inodes, iused in raw.fs:
        yield Reading(metric="disk.total_bytes", instance=mount, value=size * KIB)
        yield Reading(metric="disk.used_bytes", instance=mount, value=used * KIB)
        if used + avail > 0:
            yield Reading(metric="disk.used_percent", instance=mount, value=used / (used + avail) * 100)
        if inodes > 0:
            yield Reading(metric="disk.inodes_used_percent", instance=mount, value=iused / inodes * 100)


def _counted(raw: Raw) -> dict[str, Sequence[int]]:
    """The counter rows rates are computed from, by name."""
    rows: dict[str, Sequence[int]] = {f"cpu:{name}": counters for name, *counters in raw.cpu}
    rows |= {f"net:{name}": counters for name, *counters in raw.net if counted_interface(name)}
    rows |= {f"disk:{name}": counters for name, *counters in raw.disk if whole_disk(name)}
    return rows


def _comparable(previous: Raw, current: Raw) -> bool:
    if current.uptime <= previous.uptime:
        return False
    before, after = _counted(previous), _counted(current)
    shared = before.keys() & after.keys()
    return all(now >= then for name in shared for then, now in zip(before[name], after[name], strict=True))


def _rates(previous: Raw, current: Raw, dt: float) -> Iterable[Reading]:
    before = {name: counters for name, *counters in previous.cpu}
    for name, *counters in current.cpu:
        if name not in before:
            continue
        u, n, sy, idle, io, irq, sirq, st = (now - then for now, then in zip(counters, before[name], strict=True))
        total = u + n + sy + idle + io + irq + sirq + st
        if total == 0:
            continue
        instance = "" if name == "cpu" else name
        yield Reading(metric="cpu.used_percent", instance=instance, value=_percent((total - idle - io) / total))
        if name == "cpu":
            yield Reading(metric="cpu.user_percent", value=_percent((u + n) / total))
            yield Reading(metric="cpu.system_percent", value=_percent((sy + irq + sirq) / total))
            yield Reading(metric="cpu.iowait_percent", value=_percent(io / total))
            yield Reading(metric="cpu.steal_percent", value=_percent(st / total))

    nets = {name: (rx, tx) for name, rx, tx in previous.net}
    for name, rx, tx in current.net:
        if counted_interface(name) and name in nets:
            rx_then, tx_then = nets[name]
            yield Reading(metric="net.rx_bytes_per_sec", instance=name, value=(rx - rx_then) / dt)
            yield Reading(metric="net.tx_bytes_per_sec", instance=name, value=(tx - tx_then) / dt)

    disks = {name: (read, written, io_ms) for name, read, written, io_ms in previous.disk}
    for name, read, written, io_ms in current.disk:
        if whole_disk(name) and name in disks:
            read_then, written_then, io_ms_then = disks[name]
            yield Reading(metric="diskio.read_bytes_per_sec", instance=name, value=(read - read_then) * SECTOR / dt)
            yield Reading(
                metric="diskio.write_bytes_per_sec", instance=name, value=(written - written_then) * SECTOR / dt
            )
            busy = _percent((io_ms - io_ms_then) / (dt * 1000))
            yield Reading(metric="diskio.busy_percent", instance=name, value=busy)


def _percent(fraction: float) -> float:
    return min(max(fraction * 100, 0.0), 100.0)
