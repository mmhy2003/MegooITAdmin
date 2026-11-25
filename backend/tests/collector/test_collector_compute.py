from typing import Any

from app.collector.compute import readings
from app.collector.parse import Raw
from app.metrics.samples import Reading

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
FIRST = Raw.model_validate(FIRST_DATA)
SECOND = Raw.model_validate(SECOND_DATA)

ALWAYS = {
    ("load.1m", ""): 0.5,
    ("load.5m", ""): 0.25,
    ("load.15m", ""): 0.125,
    ("mem.total_bytes", ""): 8192000000,
    ("mem.available_bytes", ""): 6144000000,
    ("mem.used_bytes", ""): 2048000000,
    ("mem.used_percent", ""): 25.0,
    ("swap.total_bytes", ""): 1024000000,
    ("swap.used_bytes", ""): 256000000,
    ("disk.total_bytes", "/"): 102400000,
    ("disk.used_bytes", "/"): 40960000,
    ("disk.used_percent", "/"): 40.0,
    ("disk.inodes_used_percent", "/"): 25.0,
}
RATES = {
    ("cpu.used_percent", ""): 18.75,
    ("cpu.used_percent", "cpu0"): 18.75,
    ("cpu.user_percent", ""): 12.5,
    ("cpu.system_percent", ""): 6.25,
    ("cpu.iowait_percent", ""): 6.25,
    ("cpu.steal_percent", ""): 0.0,
    ("net.rx_bytes_per_sec", "eth0"): 1000.0,
    ("net.tx_bytes_per_sec", "eth0"): 2000.0,
    ("diskio.read_bytes_per_sec", "sda"): 1048576.0,
    ("diskio.write_bytes_per_sec", "sda"): 2097152.0,
    ("diskio.busy_percent", "sda"): 50.0,
}


def _by_key(result: tuple[Reading, ...]) -> dict[tuple[str, str], float]:
    values = {(reading.metric, reading.instance): reading.value for reading in result}
    assert len(values) == len(result), "a reading appears twice"
    return values


def _second(**changes: Any) -> Raw:
    return Raw.model_validate({**SECOND_DATA, **changes})


def test_the_first_sample_carries_only_load_memory_and_filesystems() -> None:
    assert _by_key(readings(None, FIRST)) == ALWAYS


def test_two_samples_give_the_expected_rates() -> None:
    assert _by_key(readings(FIRST, SECOND)) == ALWAYS | RATES


def test_a_counter_that_went_down_skips_every_rate() -> None:
    went_down = _second(net=[["eth0", 999, 12000], ["lo", 5, 5], ["veth1", 5, 5]])

    assert _by_key(readings(FIRST, went_down)) == ALWAYS


def test_an_uptime_that_went_back_skips_every_rate() -> None:
    rebooted = _second(uptime=3.0)

    assert _by_key(readings(FIRST, rebooted)) == ALWAYS


def test_loopback_veth_partitions_loop_and_device_mapper_are_left_out() -> None:
    instances = {instance for _, instance in _by_key(readings(FIRST, SECOND))}

    assert instances == {"", "cpu0", "/", "eth0", "sda"}


def test_a_filesystem_without_inodes_has_no_inode_percentage() -> None:
    btrfs = _second(fs=[["/", 100000, 40000, 60000, 0, 0]])

    values = _by_key(readings(None, btrfs))

    assert ("disk.inodes_used_percent", "/") not in values
    assert values[("disk.used_percent", "/")] == 40.0


def test_memory_without_mem_available_has_no_available_or_used() -> None:
    old_kernel = _second(mem={"total": 8000000, "available": 0, "swap_total": 1000000, "swap_free": 750000})

    values = _by_key(readings(None, old_kernel))

    assert values[("mem.total_bytes", "")] == 8192000000
    for metric in ("mem.available_bytes", "mem.used_bytes", "mem.used_percent"):
        assert (metric, "") not in values
