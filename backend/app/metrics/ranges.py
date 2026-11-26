"""The time ranges of the charts and the metrics they may ask for.

Each range reads the finest data that is still kept for its whole window (raw samples 48 hours, 1-minute rollups
30 days, 1-hour rollups 13 months) and has a step that gives at most about 360 points per line. Live reads every
raw sample of the last 15 minutes, and the WebSocket carries it on from there.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

RangeName = Literal["live", "1h", "6h", "24h", "7d", "30d", "1y"]
Source = Literal["raw", "1m", "1h"]


@dataclass(frozen=True)
class Range:
    name: RangeName
    window: timedelta
    source: Source
    step: timedelta | None  # None: every sample (live)


RANGES: dict[str, Range] = {
    "live": Range("live", timedelta(minutes=15), "raw", None),
    "1h": Range("1h", timedelta(hours=1), "raw", timedelta(seconds=10)),
    "6h": Range("6h", timedelta(hours=6), "1m", timedelta(minutes=1)),
    "24h": Range("24h", timedelta(hours=24), "1m", timedelta(minutes=5)),
    "7d": Range("7d", timedelta(days=7), "1m", timedelta(minutes=30)),
    "30d": Range("30d", timedelta(days=30), "1h", timedelta(hours=2)),
    "1y": Range("1y", timedelta(days=365), "1h", timedelta(days=1)),
}
MAX_METRICS = 16

MetricName = Literal[
    "load.1m", "load.5m", "load.15m", "mem.total_bytes", "mem.available_bytes", "mem.used_bytes", "mem.used_percent",
    "swap.total_bytes", "swap.used_bytes", "disk.total_bytes", "disk.used_bytes", "disk.used_percent",
    "disk.inodes_used_percent", "cpu.used_percent", "cpu.user_percent", "cpu.system_percent", "cpu.iowait_percent",
    "cpu.steal_percent", "net.rx_bytes_per_sec", "net.tx_bytes_per_sec", "diskio.read_bytes_per_sec",
    "diskio.write_bytes_per_sec", "diskio.busy_percent",
]
# Every metric the collector writes (app/collector/compute.py).
METRIC_NAMES = frozenset({
    "load.1m", "load.5m", "load.15m", "mem.total_bytes", "mem.available_bytes", "mem.used_bytes", "mem.used_percent",
    "swap.total_bytes", "swap.used_bytes", "disk.total_bytes", "disk.used_bytes", "disk.used_percent",
    "disk.inodes_used_percent", "cpu.used_percent", "cpu.user_percent", "cpu.system_percent", "cpu.iowait_percent",
    "cpu.steal_percent", "net.rx_bytes_per_sec", "net.tx_bytes_per_sec", "diskio.read_bytes_per_sec",
    "diskio.write_bytes_per_sec", "diskio.busy_percent",
})
