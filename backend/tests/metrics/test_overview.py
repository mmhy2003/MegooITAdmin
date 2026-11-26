import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

from app.metrics.fanout import encode
from app.metrics.overview import Disk, Overview, iso, overview_message, summarize
from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)
SERVER_ID = uuid.UUID("0b6c5f7e-2a51-4c1e-9d43-7a8f9e1c2b3d")


def _sample(*readings: tuple[str, str, float], time: datetime = NOW) -> Sample:
    return Sample(
        time=time,
        server_id=SERVER_ID,
        readings=tuple(Reading(metric=m, instance=i, value=v) for m, i, v in readings),
    )


def test_a_sample_gives_its_six_numbers():
    sample = _sample(
        ("cpu.used_percent", "", 12.5),
        ("cpu.used_percent", "cpu0", 99.0),
        ("mem.used_percent", "", 40.0),
        ("load.1m", "", 0.5),
        ("disk.used_percent", "/", 40.0),
        ("disk.used_percent", "/var", 91.0),
        ("net.rx_bytes_per_sec", "eth0", 100.0),
        ("net.rx_bytes_per_sec", "eth1", 50.0),
        ("net.tx_bytes_per_sec", "eth0", 10.0),
        ("net.tx_bytes_per_sec", "eth1", 5.0),
    )

    assert summarize(sample) == Overview(
        server_id=SERVER_ID, time=NOW, cpu=12.5, mem=40.0, load=0.5, disk=Disk("/var", 91.0), rx=150.0, tx=15.0
    )


def test_a_tie_on_disk_goes_to_the_mount_that_sorts_first():
    sample = _sample(("disk.used_percent", "/var", 70.0), ("disk.used_percent", "/", 70.0))

    assert summarize(sample).disk == Disk("/", 70.0)


def test_a_first_sample_has_no_cpu_and_no_network():
    overview = summarize(_sample(("mem.used_percent", "", 25.0), ("load.1m", "", 0.5)))

    assert (overview.cpu, overview.rx, overview.tx, overview.disk) == (None, None, None, None)
    assert (overview.mem, overview.load) == (25.0, 0.5)


def test_the_message_is_the_designs_json():
    overview = Overview(
        server_id=SERVER_ID, time=NOW, cpu=12.5, mem=40.0, load=0.5, disk=Disk("/var", 91.0), rx=150.0, tx=15.0
    )

    assert json.loads(json.dumps(overview_message(overview))) == {
        "type": "overview",
        "server_id": "0b6c5f7e-2a51-4c1e-9d43-7a8f9e1c2b3d",
        "time": "2026-11-25T10:00:05Z",
        "cpu": 12.5,
        "mem": 40.0,
        "load": 0.5,
        "disk": {"mount": "/var", "percent": 91.0},
        "rx": 150.0,
        "tx": 15.0,
    }


def test_a_message_without_disk_or_time_has_nulls():
    overview = Overview(server_id=SERVER_ID, time=None, cpu=None, mem=None, load=None, disk=None, rx=None, tx=None)

    message = overview_message(overview)

    assert (message["time"], message["disk"]) == (None, None)


def test_iso_writes_utc_with_z_like_the_fanout():
    cairo = datetime(2026, 11, 25, 12, 0, 5, 250000, tzinfo=timezone(timedelta(hours=2)))

    assert iso(cairo) == "2026-11-25T10:00:05.250000Z"
    assert iso(cairo) == json.loads(encode(_sample(time=cairo)))["time"]
