"""A server's six overview numbers: CPU, memory, load, its fullest filesystem and its network in and out.

The Dashboard shows them for every server on screen, so the backend sums them up from each sample and the browser
does not download per-core and per-device readings it would not show. A number the sample does not carry is None:
the first sample after a start has no rates yet, so it has no CPU and no network.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.metrics.samples import Sample

OVERVIEW_METRICS = ("cpu.used_percent", "mem.used_percent", "load.1m", "disk.used_percent",
                    "net.rx_bytes_per_sec", "net.tx_bytes_per_sec")


@dataclass(frozen=True)
class Disk:
    mount: str
    percent: float


@dataclass(frozen=True)
class Overview:
    server_id: uuid.UUID
    time: datetime | None
    cpu: float | None  # cpu.used_percent, instance ""
    mem: float | None  # mem.used_percent
    load: float | None  # load.1m
    disk: Disk | None  # highest disk.used_percent; a tie goes to the mount that sorts first
    rx: float | None  # sum of net.rx_bytes_per_sec over instances; None when the sample has none
    tx: float | None


def summarize(sample: Sample) -> Overview:
    cpu = mem = load = rx = tx = None
    disk: Disk | None = None
    for reading in sample.readings:
        metric, instance, value = reading.metric, reading.instance, reading.value
        if metric == "cpu.used_percent" and instance == "":
            cpu = value
        elif metric == "mem.used_percent":
            mem = value
        elif metric == "load.1m":
            load = value
        elif metric == "disk.used_percent":
            if disk is None or (-value, instance) < (-disk.percent, disk.mount):
                disk = Disk(instance, value)
        elif metric == "net.rx_bytes_per_sec":
            rx = (rx or 0.0) + value
        elif metric == "net.tx_bytes_per_sec":
            tx = (tx or 0.0) + value
    return Overview(server_id=sample.server_id, time=sample.time, cpu=cpu, mem=mem, load=load, disk=disk, rx=rx, tx=tx)


def iso(value: datetime) -> str:
    """The time in UTC with a "Z", as every message of the live feed writes it."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def overview_message(o: Overview) -> dict:
    return {
        "type": "overview",
        "server_id": str(o.server_id),
        "time": None if o.time is None else iso(o.time),
        "cpu": o.cpu,
        "mem": o.mem,
        "load": o.load,
        "disk": None if o.disk is None else {"mount": o.disk.mount, "percent": o.disk.percent},
        "rx": o.rx,
        "tx": o.tx,
    }
