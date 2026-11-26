"""The alert engine on its own: rules, servers and samples in, transitions out, with fixed times and no database."""

import uuid
from datetime import UTC, datetime, timedelta

from app.collector.alerts.engine import Engine, Firing, Rule, ServerInfo
from app.metrics.samples import Reading

T0 = datetime(2026, 11, 26, 12, tzinfo=UTC)
GROUP = uuid.uuid4()
WEB = ServerInfo(id=uuid.uuid4(), group_id=GROUP, name="web-01")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def rule(**kw) -> Rule:
    values = {
        "id": uuid.uuid4(),
        "name": "Memory almost full",
        "metric": "mem.used_percent",
        "comparison": "above",
        "threshold": 90.0,
        "duration_seconds": 60,
        "severity": "warning",
        "server_group_id": None,
        "server_id": None,
        "enabled": True,
        "revision": 1,
    }
    return Rule(**(values | kw))


def readings(**values: float) -> list[Reading]:
    """readings(mem=95) gives mem.used_percent 95 for the whole server."""
    names = {"mem": "mem.used_percent", "cpu": "cpu.used_percent", "load1": "load.1m"}
    return [Reading(metric=names[name], value=value) for name, value in values.items()]


def disk(**mounts: float) -> list[Reading]:
    """disk(root=95, var=10) gives disk.used_percent for / and /var."""
    return [
        Reading(metric="disk.used_percent", instance="/" if name == "root" else f"/{name}", value=value)
        for name, value in mounts.items()
    ]


def engine(*rules: Rule, servers: tuple[ServerInfo, ...] = (WEB,)) -> Engine:
    e = Engine()
    e.set_servers(servers, {s.id for s in servers}, T0)
    e.set_rules(rules, T0)
    return e


def every_10_s(e: Engine, values: list[list[Reading]], *, server: ServerInfo = WEB, cores: int = 1, start: float = 0):
    """Feeds one sample every 10 s and gives the transitions of each."""
    return [e.observe(server.id, r, cores, at(start + 10 * i)) for i, r in enumerate(values)]


def test_fires_only_after_the_full_duration():
    r = rule(duration_seconds=60)
    e = engine(r)

    steps = every_10_s(e, [readings(mem=95)] * 7)

    assert all(t == [] for t in steps[:6])
    [fired] = steps[6]
    assert fired.kind == "fired"
    assert fired.at == at(60)
    assert fired.rule == r
    assert fired.server == WEB
    assert fired.instance == ""
    assert fired.firing.value == fired.firing.last_value == fired.firing.peak_value == 95
    assert fired.firing.fired_at == at(60)
    assert fired.firing.rule_name == "Memory almost full"
    assert fired.firing.snapshot == ("mem.used_percent", "above", 90.0, 60, "warning")
    assert fired.alert_id == fired.firing.alert_id
    assert e.firing() == [fired.firing]


def test_a_single_good_sample_starts_the_count_again():
    e = engine(rule(duration_seconds=60))

    steps = every_10_s(e, [readings(mem=95)] * 5 + [readings(mem=50)] + [readings(mem=95)] * 7)

    assert all(t == [] for t in steps[:12])
    [fired] = steps[12]
    assert fired.at == at(120)


def test_duration_0_fires_at_the_first_sample():
    e = engine(rule(duration_seconds=0))

    [fired] = e.observe(WEB.id, readings(mem=91), 1, T0)

    assert fired.kind == "fired"
    assert fired.at == T0


def test_below_fires_under_the_threshold():
    e = engine(rule(comparison="below", threshold=10.0, duration_seconds=0))

    assert e.observe(WEB.id, readings(mem=10), 1, at(0)) == []
    [fired] = e.observe(WEB.id, readings(mem=9.5), 1, at(10))

    assert fired.kind == "fired"
    assert fired.firing.value == 9.5


def test_each_filesystem_is_its_own_alert():
    e = engine(rule(metric="disk.used_percent", duration_seconds=0))

    first = e.observe(WEB.id, disk(root=95, var=10, srv=92), 1, at(0))
    second = e.observe(WEB.id, disk(root=95, var=93, srv=92), 1, at(10))

    assert sorted(t.instance for t in first) == ["/", "/srv"]
    assert [t.instance for t in second] == ["/var"]
    assert len({t.alert_id for t in first + second}) == 3
    assert sorted(f.instance for f in e.firing()) == ["/", "/srv", "/var"]


def test_load_is_compared_per_core():
    e = engine(rule(metric="load.1m", threshold=1.0, duration_seconds=0))

    assert e.observe(WEB.id, readings(load1=3.0), 4, at(0)) == []
    [fired] = e.observe(WEB.id, readings(load1=6.0), 4, at(10))
    assert fired.firing.value == 1.5

    other = ServerInfo(id=uuid.uuid4(), group_id=GROUP, name="db-01")
    e = engine(rule(metric="load.1m", threshold=1.0, duration_seconds=0), servers=(other,))
    [fired] = e.observe(other.id, readings(load1=1.5), 0, at(0))  # no cores known: counted as one
    assert fired.firing.value == 1.5


def test_a_missing_whole_server_value_changes_nothing():
    e = engine(rule(duration_seconds=20))

    e.observe(WEB.id, readings(mem=95), 1, at(0))
    assert e.observe(WEB.id, readings(cpu=10), 1, at(10)) == []  # mem missing: the count goes on
    [fired] = e.observe(WEB.id, readings(mem=95), 1, at(20))
    assert fired.at == at(20)

    assert e.observe(WEB.id, readings(cpu=10), 1, at(30)) == []  # mem missing: still firing
    assert len(e.firing()) == 1


def test_a_vanished_filesystem_resolves_its_alert():
    e = engine(rule(metric="disk.used_percent", duration_seconds=0))

    [fired] = e.observe(WEB.id, disk(root=10, mnt=95), 1, at(0))
    e.observe(WEB.id, disk(root=10, mnt=97), 1, at(10))
    [resolved] = e.observe(WEB.id, disk(root=10), 1, at(20))

    assert resolved.kind == "resolved"
    assert resolved.alert_id == fired.alert_id
    assert resolved.instance == "/mnt"
    assert resolved.at == at(20)
    assert resolved.firing.last_value == 97
    assert resolved.firing.peak_value == 97
    assert e.firing() == []


def test_resolve_carries_the_last_value_and_the_peak():
    e = engine(rule(duration_seconds=0))
    [fired] = e.observe(WEB.id, readings(mem=92), 1, at(0))
    e.observe(WEB.id, readings(mem=99), 1, at(10))
    e.observe(WEB.id, readings(mem=94), 1, at(20))
    [resolved] = e.observe(WEB.id, readings(mem=40), 1, at(30))

    assert resolved.kind == "resolved"
    assert resolved.rule is None
    assert resolved.alert_id == fired.alert_id
    assert (resolved.firing.value, resolved.firing.last_value, resolved.firing.peak_value) == (92, 40, 99)

    low = engine(rule(comparison="below", threshold=10.0, duration_seconds=0))
    low.observe(WEB.id, readings(mem=8), 1, at(0))
    low.observe(WEB.id, readings(mem=3), 1, at(10))
    low.observe(WEB.id, readings(mem=6), 1, at(20))
    [resolved] = low.observe(WEB.id, readings(mem=50), 1, at(30))
    assert (resolved.firing.value, resolved.firing.last_value, resolved.firing.peak_value) == (8, 50, 3)


def test_a_gap_of_more_than_30_s_starts_the_count_again():
    e = engine(rule(duration_seconds=60))

    e.observe(WEB.id, readings(mem=95), 1, at(0))
    e.observe(WEB.id, readings(mem=95), 1, at(30))  # exactly 30 s: the count goes on
    assert e.observe(WEB.id, readings(mem=95), 1, at(61)) == []  # 31 s later: it starts again here
    assert e.observe(WEB.id, readings(mem=95), 1, at(91)) == []
    [fired] = e.observe(WEB.id, readings(mem=95), 1, at(121))
    assert fired.at == at(121)


def test_a_disabled_rule_is_not_evaluated():
    e = engine(rule(enabled=False, duration_seconds=0))

    assert e.observe(WEB.id, readings(mem=99), 1, at(0)) == []
    assert e.firing() == []


def test_scope_by_all_group_and_server():
    other_group = uuid.uuid4()
    db = ServerInfo(id=uuid.uuid4(), group_id=other_group, name="db-01")
    everywhere = rule(name="all", duration_seconds=0)
    group_only = rule(name="group", duration_seconds=0, server_group_id=other_group)
    server_only = rule(name="server", duration_seconds=0, server_id=WEB.id)
    e = engine(everywhere, group_only, server_only, servers=(WEB, db))

    on_web = e.observe(WEB.id, readings(mem=99), 1, at(0))
    on_db = e.observe(db.id, readings(mem=99), 1, at(0))

    assert sorted(t.rule.name for t in on_web) == ["all", "server"]
    assert sorted(t.rule.name for t in on_db) == ["all", "group"]
    assert everywhere.applies_to(WEB) and everywhere.applies_to(db)
    assert group_only.applies_to(db) and not group_only.applies_to(WEB)
    assert server_only.applies_to(WEB) and not server_only.applies_to(db)


def test_an_unknown_server_is_ignored():
    e = engine(rule(duration_seconds=0))

    assert e.observe(uuid.uuid4(), readings(mem=99), 1, at(0)) == []
    assert e.firing() == []


def unreachable_rule(**kw) -> Rule:
    return rule(**({"name": "Server unreachable", "metric": "unreachable", "comparison": None, "threshold": None,
                    "duration_seconds": 300, "severity": "critical"} | kw))


def fire(e: Engine, r: Rule, value: float = 95, *, server: ServerInfo = WEB, start: float = 0):
    """Fires r on server with one sample (r has duration 0) and gives the fired transition."""
    [fired] = e.observe(server.id, readings(mem=value), 1, at(start))
    assert fired.kind == "fired" and fired.rule == r
    return fired


def test_unreachable_fires_after_its_duration_from_the_status_time():
    r = unreachable_rule(duration_seconds=300)
    e = engine(r)
    since = at(30)

    assert e.unreachable(WEB.id, since, at(300)) == []
    assert e.unreachable(WEB.id, since, at(329)) == []
    [fired] = e.unreachable(WEB.id, since, at(330))
    assert e.unreachable(WEB.id, since, at(340)) == []  # already firing

    assert fired.kind == "fired"
    assert fired.at == at(330)
    assert fired.rule == r
    assert fired.server == WEB
    assert fired.instance == ""
    assert (fired.firing.value, fired.firing.last_value, fired.firing.peak_value) == (None, None, None)
    assert fired.firing.snapshot == ("unreachable", None, None, 300, "critical")
    assert e.firing() == [fired.firing]

    assert engine(unreachable_rule(enabled=False)).unreachable(WEB.id, since, at(1000)) == []
    assert engine(unreachable_rule(server_id=uuid.uuid4())).unreachable(WEB.id, since, at(1000)) == []
    assert engine(rule(duration_seconds=0)).unreachable(WEB.id, since, at(1000)) == []  # a metric rule
    assert engine(unreachable_rule()).unreachable(uuid.uuid4(), since, at(1000)) == []  # an unknown server


def test_a_sample_resolves_an_unreachable_alert():
    e = engine(unreachable_rule(duration_seconds=0), rule(duration_seconds=60))
    [fired] = e.unreachable(WEB.id, at(0), at(0))

    [resolved] = e.observe(WEB.id, readings(mem=99), 1, at(10))

    assert resolved.kind == "resolved"
    assert resolved.alert_id == fired.alert_id
    assert resolved.at == at(10)
    assert (resolved.firing.value, resolved.firing.last_value, resolved.firing.peak_value) == (None, None, None)
    assert e.firing() == []


def test_a_changed_rule_ends_its_alert():
    r = rule(duration_seconds=0)
    e = engine(r)
    fired = fire(e, r)
    e.observe(WEB.id, readings(mem=97), 1, at(10))

    [ended] = e.set_rules([rule(id=r.id, threshold=95.0, duration_seconds=0, revision=2)], at(15))

    assert ended.kind == "ended"
    assert ended.end_reason == "rule_changed"
    assert ended.alert_id == fired.alert_id
    assert ended.at == at(15)
    assert ended.server == WEB
    assert ended.rule is None
    assert (ended.firing.value, ended.firing.last_value, ended.firing.peak_value) == (95, 97, 97)
    assert e.firing() == []

    for change in ({"severity": "critical"}, {"duration_seconds": 30}, {"comparison": "below", "threshold": 99.0}):
        r = rule(duration_seconds=0)
        e = engine(r)
        fire(e, r)
        [ended] = e.set_rules([rule(**({"id": r.id, "duration_seconds": 0, "revision": 2} | change))], at(15))
        assert ended.end_reason == "rule_changed", change


def test_a_rule_scoped_away_from_the_server_ends_its_alert():
    r = rule(duration_seconds=0)
    e = engine(r)
    fired = fire(e, r)

    [ended] = e.set_rules([rule(id=r.id, duration_seconds=0, server_group_id=uuid.uuid4(), revision=2)], at(15))

    assert ended.kind == "ended"
    assert ended.end_reason == "rule_changed"
    assert ended.alert_id == fired.alert_id


def test_a_disabled_rule_ends_its_alert():
    r = rule(duration_seconds=0)
    e = engine(r)
    fired = fire(e, r)

    [ended] = e.set_rules([rule(id=r.id, duration_seconds=0, enabled=False, revision=2)], at(15))

    assert (ended.kind, ended.end_reason, ended.alert_id) == ("ended", "rule_disabled", fired.alert_id)
    assert e.firing() == []


def test_a_deleted_rule_ends_its_alert():
    r = rule(duration_seconds=0)
    kept = rule(name="kept", duration_seconds=0)
    e = engine(r, kept)
    fired = [t for t in e.observe(WEB.id, readings(mem=95), 1, at(0)) if t.rule == r][0]

    [ended] = e.set_rules([kept], at(15))

    assert (ended.kind, ended.end_reason, ended.alert_id) == ("ended", "rule_deleted", fired.alert_id)
    assert [f.rule_id for f in e.firing()] == [kept.id]


def test_a_renamed_rule_ends_nothing_and_later_fires_carry_the_new_name():
    r = rule(duration_seconds=0)
    e = engine(r)
    fired = fire(e, r)
    renamed = rule(id=r.id, name="RAM almost full", duration_seconds=0, revision=2)

    assert e.set_rules([renamed], at(15)) == []
    assert [f.rule_name for f in e.firing()] == ["Memory almost full"]

    [resolved] = e.observe(WEB.id, readings(mem=50), 1, at(20))
    assert resolved.alert_id == fired.alert_id
    [again] = e.observe(WEB.id, readings(mem=95), 1, at(30))
    assert again.firing.rule_name == "RAM almost full"
    assert again.rule == renamed


def test_a_new_revision_starts_counting_again():
    r = rule(duration_seconds=60)
    e = engine(r)
    every_10_s(e, [readings(mem=95)] * 5)  # counting since 0 s, up to 40 s

    assert e.set_rules([rule(id=r.id, name="Renamed", duration_seconds=60, revision=2)], at(45)) == []
    steps = every_10_s(e, [readings(mem=95)] * 7, start=50)

    assert all(t == [] for t in steps[:6])
    [fired] = steps[6]
    assert fired.at == at(110)  # 60 s after the first sample of the new revision


def test_a_server_not_monitored_ends_its_alerts():
    db = ServerInfo(id=uuid.uuid4(), group_id=GROUP, name="db-01")
    r = rule(duration_seconds=0)
    slow = rule(name="slow", metric="cpu.used_percent", duration_seconds=60)
    e = engine(r, slow, servers=(WEB, db))
    on_web = fire(e, r)
    e.observe(WEB.id, readings(cpu=99), 1, at(0))  # counting on WEB
    on_db = [t for t in e.observe(db.id, readings(mem=95, cpu=99), 1, at(0)) if t.rule == r][0]

    [ended] = e.set_servers((WEB, db), {db.id}, at(15))

    assert (ended.kind, ended.end_reason, ended.alert_id) == ("ended", "server_not_monitored", on_web.alert_id)
    assert ended.server == WEB
    assert ended.at == at(15)
    assert [f.alert_id for f in e.firing()] == [on_db.alert_id]

    # Monitored again: WEB's counting started over, db's goes on.
    assert e.set_servers((WEB, db), {WEB.id, db.id}, at(20)) == []
    assert e.observe(WEB.id, readings(cpu=99), 1, at(30)) == []
    assert e.observe(db.id, readings(mem=95, cpu=99), 1, at(30)) == []
    assert e.observe(WEB.id, readings(cpu=99), 1, at(60)) == []  # counting since 30 s
    assert [t.rule for t in e.observe(db.id, readings(mem=95, cpu=99), 1, at(60))] == [slow]


def test_a_removed_server_is_forgotten_without_transitions():
    db = ServerInfo(id=uuid.uuid4(), group_id=GROUP, name="db-01")
    r = rule(duration_seconds=0)
    e = engine(r, servers=(WEB, db))
    fire(e, r)
    on_db = fire(e, r, server=db)

    assert e.set_servers((db,), {db.id}, at(15)) == []

    assert [f.alert_id for f in e.firing()] == [on_db.alert_id]
    assert e.observe(WEB.id, readings(mem=50), 1, at(20)) == []  # no longer known


def loaded(r: Rule | None, **kw) -> Firing:
    values = {
        "alert_id": uuid.uuid4(),
        "rule_id": r.id if r else None,
        "server_id": WEB.id,
        "instance": "",
        "snapshot": r.snapshot() if r else ("mem.used_percent", "above", 90.0, 0, "warning"),
        "rule_name": r.name if r else "Gone",
        "fired_at": T0 - timedelta(hours=1),
        "value": 93.0,
        "last_value": 96.0,
        "peak_value": 98.0,
    }
    return Firing(**(values | kw))


def test_loaded_firing_alerts_resolve_normally():
    r = rule(duration_seconds=0)
    root = rule(name="disk", metric="disk.used_percent", duration_seconds=0)
    down = unreachable_rule()
    mem, slash = loaded(r), loaded(root, instance="/")
    down_firing = loaded(down, value=None, last_value=None, peak_value=None)
    e = Engine()
    e.load_firing([mem, slash, down_firing])
    assert e.set_servers((WEB,), {WEB.id}, T0) == []
    assert e.set_rules([r, root, down], T0) == []
    assert e.unreachable(WEB.id, T0 - timedelta(hours=1), T0) == []  # firing already: no second alert

    [back] = e.observe(WEB.id, readings(mem=99) + disk(root=95), 1, at(0))  # firing already: no new metric alert
    assert (back.kind, back.alert_id) == ("resolved", down_firing.alert_id)
    steps = e.observe(WEB.id, readings(mem=40) + disk(root=10), 1, at(10))

    assert {(t.kind, t.alert_id) for t in steps} == {("resolved", mem.alert_id), ("resolved", slash.alert_id)}
    [mem_resolved] = [t.firing for t in steps if t.alert_id == mem.alert_id]
    assert (mem_resolved.value, mem_resolved.last_value, mem_resolved.peak_value) == (93.0, 40, 99)
    assert e.firing() == []


def test_a_loaded_alert_without_a_rule_ends_as_deleted():
    one, two = loaded(None), loaded(None)  # two deleted rules' alerts on the same server and instance
    e = Engine()
    e.load_firing([one, two])
    e.set_servers((WEB,), {WEB.id}, T0)

    ended = e.set_rules([], at(5))

    assert {(t.kind, t.end_reason, t.alert_id) for t in ended} == {
        ("ended", "rule_deleted", one.alert_id),
        ("ended", "rule_deleted", two.alert_id),
    }
    assert e.firing() == []
