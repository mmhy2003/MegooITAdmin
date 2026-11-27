"""What an alert rule can watch: each metric with its label, unit and limit, and the words a rule is made of."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MetricSpec:
    label: str  # "Space used"
    unit: Literal["%", "per core", None]
    maximum: float | None  # the highest threshold: 100, 1000, None for unreachable
    per_instance: bool  # True for disk.*: one alert per mount point
    per_core: bool  # True for load.*: the value is divided by the server's cores


CATALOG: dict[str, MetricSpec] = {
    "cpu.used_percent": MetricSpec("CPU used", "%", 100, False, False),
    "mem.used_percent": MetricSpec("Memory used", "%", 100, False, False),
    "disk.used_percent": MetricSpec("Space used", "%", 100, True, False),
    "disk.inodes_used_percent": MetricSpec("Inodes used", "%", 100, True, False),
    "load.1m": MetricSpec("Load per core (1 min)", "per core", 1000, False, True),
    "load.5m": MetricSpec("Load per core (5 min)", "per core", 1000, False, True),
    "load.15m": MetricSpec("Load per core (15 min)", "per core", 1000, False, True),
    "unreachable": MetricSpec("Unreachable", None, None, False, False),
}
METRICS = tuple(CATALOG)
SEVERITIES = ("warning", "critical")
COMPARISONS = ("above", "below")
END_REASONS = ("rule_changed", "rule_disabled", "rule_deleted", "server_not_monitored")
