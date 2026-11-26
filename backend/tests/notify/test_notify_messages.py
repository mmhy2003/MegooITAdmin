from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.notify.messages import (
    TEST_TEXT,
    EventView,
    chat_text,
    duration_text,
    email_body,
    email_subject,
    event_sentence,
    generic_json,
    headline,
    rule_sentence,
    value_text,
)

FIRED_AT = datetime(2026, 11, 27, 9, 30, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 11, 27, 9, 45, tzinfo=UTC)
DISK = EventView(
    event_id=UUID("00000000-0000-0000-0000-000000000001"),
    kind="fired",
    at=FIRED_AT,
    alert_id=UUID("00000000-0000-0000-0000-000000000002"),
    severity="critical",
    rule_name="Filesystem almost full",
    metric="disk.used_percent",
    comparison="above",
    threshold=90.0,
    duration_seconds=600,
    instance="/var",
    value=93.42,
    last_value=93.42,
    fired_at=FIRED_AT,
    resolved_at=None,
    end_reason=None,
    server_id=UUID("00000000-0000-0000-0000-000000000003"),
    server_name="db-prod-01",
    group_name="Databases",
)
RESOLVED = replace(DISK, kind="resolved", at=RESOLVED_AT, last_value=71.04, resolved_at=RESOLVED_AT)


def test_duration_and_rule_sentences():
    assert duration_text(0) == ""
    assert duration_text(30) == "1 min"
    assert duration_text(600) == "10 min"
    assert duration_text(659) == "10 min"
    assert duration_text(3600) == "1 h"
    assert duration_text(7200) == "2 h"
    assert duration_text(5400) == "1 h 30 min"
    assert rule_sentence("disk.used_percent", "above", 90.0, 600) == "Space used above 90% for 10 min"
    assert rule_sentence("mem.used_percent", "above", 92.5, 0) == "Memory used above 92.5%"
    assert rule_sentence("load.5m", "above", 2.0, 900) == "Load per core (5 min) above 2 per core for 15 min"
    assert rule_sentence("disk.inodes_used_percent", "below", 10.0, 3600) == "Inodes used below 10% for 1 h"
    assert rule_sentence("unreachable", None, None, 300) == "Unreachable for 5 min"
    assert rule_sentence("unreachable", None, None, 0) == "Unreachable"
    assert value_text("cpu.used_percent", 97.25) == "97.2%"
    assert value_text("load.1m", 1.5) == "1.50 per core"


def test_headlines_per_metric():
    def of(metric: str, value: float | None, instance: str = "") -> str:
        return headline(replace(DISK, metric=metric, value=value, last_value=value, instance=instance))

    assert of("cpu.used_percent", 97.0) == "db-prod-01: CPU is 97.0% busy"
    assert of("mem.used_percent", 91.26) == "db-prod-01: memory is 91.3% used"
    assert of("disk.used_percent", 93.42, "/var") == "db-prod-01: /var is 93.4% full"
    assert of("disk.inodes_used_percent", 95.0, "/") == "db-prod-01: / has 95.0% of its inodes used"
    assert of("load.1m", 2.346) == "db-prod-01: load is 2.35 per core (1 min)"
    assert of("load.5m", 1.2) == "db-prod-01: load is 1.20 per core (5 min)"
    assert of("load.15m", 1.0) == "db-prod-01: load is 1.00 per core (15 min)"
    assert of("unreachable", None) == "db-prod-01 is unreachable"
    assert headline(RESOLVED) == "db-prod-01: /var is 71.0% full"


def test_the_email_subject_and_body():
    assert email_subject(DISK) == "[Critical] db-prod-01: /var is 93.4% full"
    assert email_body(DISK) == (
        "db-prod-01: /var is 93.4% full\n"
        "\n"
        "Rule: Filesystem almost full: Space used above 90% for 10 min\n"
        "Server: db-prod-01 (Databases)\n"
        "Fired: 2026-11-27T09:30:00+00:00"
    )
    assert email_subject(replace(RESOLVED, severity="warning")) == "[Warning] Resolved: db-prod-01: /var is 71.0% full"
    assert email_body(RESOLVED) == (
        "Resolved: db-prod-01: /var is 71.0% full\n"
        "\n"
        "Rule: Filesystem almost full: Space used above 90% for 10 min\n"
        "Server: db-prod-01 (Databases)\n"
        "Fired: 2026-11-27T09:30:00+00:00\n"
        "Resolved: 2026-11-27T09:45:00+00:00"
    )


def test_the_slack_and_telegram_text():
    assert chat_text(DISK) == "Critical: db-prod-01: /var is 93.4% full. Space used above 90% for 10 min."
    down = replace(DISK, severity="warning", metric="unreachable", comparison=None, threshold=None,
                   duration_seconds=0, instance="", value=None, last_value=None)
    assert chat_text(down) == "Warning: db-prod-01 is unreachable. Unreachable."
    assert TEST_TEXT == "MegooITAdmin test: this channel works."


def test_the_generic_json_shape():
    assert generic_json(DISK) == {
        "version": 1,
        "event": "fired",
        "text": "Critical: db-prod-01: /var is 93.4% full. Space used above 90% for 10 min.",
        "alert": {
            "id": "00000000-0000-0000-0000-000000000002",
            "severity": "critical",
            "rule_name": "Filesystem almost full",
            "metric": "disk.used_percent",
            "comparison": "above",
            "threshold": 90.0,
            "duration_seconds": 600,
            "instance": "/var",
            "value": 93.42,
            "fired_at": "2026-11-27T09:30:00+00:00",
            "resolved_at": None,
            "end_reason": None,
        },
        "server": {"id": "00000000-0000-0000-0000-000000000003", "name": "db-prod-01", "group": "Databases"},
    }
    resolved = generic_json(RESOLVED)
    assert resolved["event"] == "resolved"
    assert resolved["alert"]["value"] == 71.04
    assert resolved["alert"]["resolved_at"] == "2026-11-27T09:45:00+00:00"


def test_resolved_and_ended_sentences():
    assert event_sentence(DISK) == "db-prod-01: /var is 93.4% full"
    assert event_sentence(RESOLVED) == "Resolved: db-prod-01: /var is 71.0% full"
    down = replace(RESOLVED, metric="unreachable", comparison=None, threshold=None, instance="", value=None,
                   last_value=None)
    assert event_sentence(down) == "Resolved: db-prod-01 is reachable again"
    ended = replace(RESOLVED, kind="ended", end_reason="rule_disabled")
    assert event_sentence(ended) == "Ended: db-prod-01: Filesystem almost full, the rule was switched off"
    assert event_sentence(replace(ended, end_reason="rule_changed")).endswith(", the rule was changed")
    assert event_sentence(replace(ended, end_reason="rule_deleted")).endswith(", the rule was deleted")
    assert event_sentence(replace(ended, end_reason="server_not_monitored")).endswith(
        ", the server is no longer monitored"
    )
    assert chat_text(ended) == (
        "Critical: Ended: db-prod-01: Filesystem almost full, the rule was switched off. "
        "Space used above 90% for 10 min."
    )
