from datetime import timedelta
from typing import Any, get_args

from app.collector.compute import readings
from app.collector.parse import Raw
from app.metrics.ranges import MAX_METRICS, METRIC_NAMES, RANGES, MetricName

# The two samples of tests/collector/test_collector_compute.py: together they give every metric there is.
FIRST_DATA: dict[str, Any] = {
    "v": 1,
    "uptime": 100.0,
    "load": [0.5, 0.25, 0.125],
    "cpu": [["cpu", 100, 0, 50, 800, 50, 0, 0, 0], ["cpu0", 50, 0, 25, 400, 25, 0, 0, 0]],
    "mem": {"total": 8000000, "available": 6000000, "swap_total": 1000000, "swap_free": 750000},
    "net": [["eth0", 1000, 2000], ["lo", 5, 5], ["veth1", 5, 5]],
    "disk": [["sda", 0, 0, 0], ["sda1", 0, 0, 0], ["loop0", 0, 0, 0], ["dm-0", 0, 0, 0]],
    "fs": [["/", 100000, 40000, 60000, 1000, 250]],
}
SECOND_DATA: dict[str, Any] = {
    **FIRST_DATA,
    "uptime": 105.0,
    "cpu": [["cpu", 200, 0, 100, 1400, 100, 0, 0, 0], ["cpu0", 100, 0, 50, 700, 50, 0, 0, 0]],
    "net": [["eth0", 6000, 12000], ["lo", 5, 5], ["veth1", 5, 5]],
    "disk": [["sda", 10240, 20480, 2500], ["sda1", 0, 0, 0], ["loop0", 0, 0, 0], ["dm-0", 0, 0, 0]],
}
RETENTION = {"raw": timedelta(hours=48), "1m": timedelta(days=30), "1h": timedelta(days=395)}


def test_each_range_reads_the_finest_data_that_still_exists():
    assert {name: (r.window, r.source, r.step) for name, r in RANGES.items()} == {
        "live": (timedelta(minutes=15), "raw", None),
        "1h": (timedelta(hours=1), "raw", timedelta(seconds=10)),
        "6h": (timedelta(hours=6), "1m", timedelta(minutes=1)),
        "24h": (timedelta(hours=24), "1m", timedelta(minutes=5)),
        "7d": (timedelta(days=7), "1m", timedelta(minutes=30)),
        "30d": (timedelta(days=30), "1h", timedelta(hours=2)),
        "1y": (timedelta(days=365), "1h", timedelta(days=1)),
    }
    for name, range_ in RANGES.items():
        assert range_.name == name
        assert range_.window <= RETENTION[range_.source], name


def test_each_range_returns_at_most_about_360_points():
    for name, range_ in RANGES.items():
        if range_.step is not None:
            assert range_.window / range_.step <= 366, name


def test_metric_names_are_what_the_collector_writes():
    result = readings(Raw.model_validate(FIRST_DATA), Raw.model_validate(SECOND_DATA))

    assert {r.metric for r in result} == METRIC_NAMES


def test_the_query_literal_matches():
    assert set(get_args(MetricName)) == METRIC_NAMES
    assert MAX_METRICS == 16
