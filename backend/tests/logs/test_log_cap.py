from app.logs.cap import Batcher, Cap


def line(seq: int) -> dict:
    return {"seq": seq, "time": "2026-11-27T12:00:00Z", "text": f"line {seq}"}


def lines(*seqs: int) -> dict:
    return {"type": "lines", "lines": [line(s) for s in seqs]}


def test_the_cap_admits_per_second_and_resets_the_next_second():
    t = [100.2]
    cap = Cap(3, clock=lambda: t[0])

    assert [cap.admit() for _ in range(5)] == [True, True, True, False, False]
    t[0] = 100.9
    assert not cap.admit()
    t[0] = 101.0
    assert [cap.admit() for _ in range(4)] == [True, True, True, False]


def test_the_batcher_puts_skipped_at_the_place_of_the_gap():
    batcher = Batcher()
    batcher.keep(line(1))
    batcher.keep(line(2))
    batcher.drop()
    batcher.drop()
    batcher.keep(line(3))

    assert batcher.take() == [lines(1, 2), {"type": "skipped", "count": 2, "after_seq": 2}, lines(3)]
    assert batcher.take() == []


def test_take_emits_pending_drops():
    batcher = Batcher()
    batcher.drop()
    assert batcher.take() == [{"type": "skipped", "count": 1, "after_seq": 0}]

    batcher.keep(line(5))
    batcher.drop()
    assert batcher.take() == [lines(5), {"type": "skipped", "count": 1, "after_seq": 5}]

    batcher.drop()
    assert batcher.take() == [{"type": "skipped", "count": 1, "after_seq": 5}]


def test_full_after_max_lines():
    batcher = Batcher(max_lines=2)
    batcher.keep(line(1))
    assert not batcher.full
    batcher.drop()
    batcher.keep(line(2))
    assert batcher.full

    batcher.take()
    assert not batcher.full


def test_take_is_empty_when_nothing_waits():
    assert Batcher().take() == []
