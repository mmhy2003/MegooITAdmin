import json

import pytest

from app.collector.parse import MAX_DEVICES, MAX_LINE, Lines, Memory, parse

APPENDIX_A_LINE = (
    b'{"v":1,"uptime":12345.67,"load":[0.5,0.25,0.125],"cpu":[["cpu",100,0,50,800,50,0,0,0],'
    b'["cpu0",50,0,25,400,25,0,0,0]],"mem":{"total":8000000,"available":6000000,"swap_total":1000000,'
    b'"swap_free":750000},"net":[["eth0",1000,2000]],"disk":[["sda",0,0,0]],'
    b'"fs":[["/",100000,40000,60000,1000,250]]}'
)


def _line(**changes: object) -> bytes:
    sample = json.loads(APPENDIX_A_LINE)
    sample.update(changes)
    return json.dumps(sample).encode()


def _without(key: str) -> bytes:
    sample = json.loads(APPENDIX_A_LINE)
    del sample[key]
    return json.dumps(sample).encode()


def test_the_example_line_parses() -> None:
    raw = parse(APPENDIX_A_LINE)

    assert raw.v == 1
    assert raw.uptime == 12345.67
    assert raw.load == (0.5, 0.25, 0.125)
    assert raw.cpu == (("cpu", 100, 0, 50, 800, 50, 0, 0, 0), ("cpu0", 50, 0, 25, 400, 25, 0, 0, 0))
    assert raw.mem == Memory(total=8000000, available=6000000, swap_total=1000000, swap_free=750000)
    assert raw.net == (("eth0", 1000, 2000),)
    assert raw.disk == (("sda", 0, 0, 0),)
    assert raw.fs == (("/", 100000, 40000, 60000, 1000, 250),)


def test_a_line_split_across_chunks_is_joined() -> None:
    lines = Lines()

    assert lines.feed(APPENDIX_A_LINE[:10]) == []
    assert lines.feed(APPENDIX_A_LINE[10:100]) == []
    assert lines.feed(APPENDIX_A_LINE[100:] + b"\n" + b"next") == [APPENDIX_A_LINE]
    assert lines.feed(b"\n") == [b"next"]
    assert lines.too_long == 0


def test_a_line_longer_than_256_kb_is_skipped_and_counted_and_the_next_one_arrives() -> None:
    lines = Lines()

    assert lines.feed(b"x" * MAX_LINE) == []
    assert lines.feed(b"x" * 1000) == []
    assert lines.feed(b"x" * 1000 + b"\n" + APPENDIX_A_LINE[:50]) == []
    assert lines.feed(APPENDIX_A_LINE[50:] + b"\n") == [APPENDIX_A_LINE]
    assert lines.too_long == 1


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(b"not json", id="not json"),
        pytest.param(_line(v=2), id="version 2"),
        pytest.param(_line(net=[["eth0", -1, 2000]]), id="a negative counter"),
        pytest.param(_without("mem"), id="mem missing"),
        pytest.param(APPENDIX_A_LINE.replace(b"[0.5,0.25,0.125]", b"[NaN,0.25,0.125]"), id="NaN load"),
    ],
)
def test_malformed_lines_are_refused(line: bytes) -> None:
    with pytest.raises(ValueError):
        parse(line)


def test_too_many_devices_are_cut_to_their_limits() -> None:
    cpu = [["cpu", 1, 0, 0, 0, 0, 0, 0, 0]] + [[f"cpu{i}", 1, 0, 0, 0, 0, 0, 0, 0] for i in range(299)]
    net = [[f"eth{i}", 1, 2] for i in range(100)]

    raw = parse(_line(cpu=cpu, net=net))

    assert len(raw.cpu) == 257
    assert raw.cpu[0][0] == "cpu" and raw.cpu[-1][0] == "cpu255"
    assert len(raw.net) == MAX_DEVICES
    assert raw.net[-1][0] == "eth63"


def test_a_name_longer_than_255_characters_is_dropped() -> None:
    raw = parse(_line(net=[["e" * 256, 1, 2], ["e" * 255, 3, 4]], fs=[["/" + "a" * 255, 1, 1, 0, 1, 1]]))

    assert raw.net == (("e" * 255, 3, 4),)
    assert raw.fs == ()


def test_odd_names_are_kept_as_given() -> None:
    raw = parse(_line(net=[['eth"0', 1, 2]], fs=[["/mnt/a\\b", 1, 1, 0, 1, 1], ["/média", 1, 1, 0, 1, 1]]))

    assert raw.net[0][0] == 'eth"0'
    assert [row[0] for row in raw.fs] == ["/mnt/a\\b", "/média"]
