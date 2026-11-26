"""The words of alert messages: one alert event in, the email, chat and JSON texts out. The frontend says the same."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.alerts.catalog import CATALOG

TEST_TEXT = "MegooITAdmin test: this channel works."

SEVERITY_WORD = {"warning": "Warning", "critical": "Critical"}
END_REASON_TEXT = {
    "rule_changed": "the rule was changed",
    "rule_disabled": "the rule was switched off",
    "rule_deleted": "the rule was deleted",
    "server_not_monitored": "the server is no longer monitored",
}
LOAD_WINDOW = {"load.1m": "1 min", "load.5m": "5 min", "load.15m": "15 min"}


@dataclass(frozen=True)
class EventView:
    """One alert event with its alert, server and group, as a message tells it."""

    event_id: UUID
    kind: str  # "fired", "resolved" or "ended"
    at: datetime
    alert_id: UUID
    severity: str
    rule_name: str
    metric: str
    comparison: str | None
    threshold: float | None
    duration_seconds: int
    instance: str
    value: float | None
    last_value: float | None
    fired_at: datetime
    resolved_at: datetime | None
    end_reason: str | None
    server_id: UUID
    server_name: str
    group_name: str

    @property
    def shown_value(self) -> float | None:
        """The fired value, or the last one when the alert resolved."""
        return self.last_value if self.kind == "resolved" else self.value


def duration_text(seconds: int) -> str:
    if seconds == 0:
        return ""
    hours, rest = divmod(seconds, 3600)
    if hours and not rest:
        return f"{hours} h"
    if hours:
        return f"{hours} h {rest // 60} min"
    return f"{max(seconds // 60, 1)} min"


def number(x: float) -> str:
    return format(x, "g")


def rule_sentence(metric: str, comparison: str | None, threshold: float | None, duration_seconds: int) -> str:
    duration = f" for {duration_text(duration_seconds)}" if duration_seconds else ""
    if metric == "unreachable":
        return f"Unreachable{duration}"
    spec = CATALOG[metric]
    unit = "%" if spec.unit == "%" else " per core"
    return f"{spec.label} {comparison} {number(threshold)}{unit}{duration}"


def value_text(metric: str, value: float) -> str:
    if CATALOG[metric].unit == "%":
        return f"{value:.1f}%"
    return f"{value:.2f} per core"


def headline(view: EventView) -> str:
    server, metric = view.server_name, view.metric
    if metric == "unreachable":
        return f"{server} is unreachable"
    value = value_text(metric, view.shown_value)
    if metric == "cpu.used_percent":
        return f"{server}: CPU is {value} busy"
    if metric == "mem.used_percent":
        return f"{server}: memory is {value} used"
    if metric == "disk.used_percent":
        return f"{server}: {view.instance} is {value} full"
    if metric == "disk.inodes_used_percent":
        return f"{server}: {view.instance} has {value} of its inodes used"
    return f"{server}: load is {value} ({LOAD_WINDOW[metric]})"


def event_sentence(view: EventView) -> str:
    if view.kind == "ended":
        return f"Ended: {view.server_name}: {view.rule_name}, {END_REASON_TEXT[view.end_reason]}"
    if view.kind == "resolved":
        if view.metric == "unreachable":
            return f"Resolved: {view.server_name} is reachable again"
        return f"Resolved: {headline(view)}"
    return headline(view)


def _rule_sentence(view: EventView) -> str:
    return rule_sentence(view.metric, view.comparison, view.threshold, view.duration_seconds)


def email_subject(view: EventView) -> str:
    return f"[{SEVERITY_WORD[view.severity]}] {event_sentence(view)}"


def email_body(view: EventView) -> str:
    lines = [
        event_sentence(view),
        "",
        f"Rule: {view.rule_name}: {_rule_sentence(view)}",
        f"Server: {view.server_name} ({view.group_name})",
        f"Fired: {view.fired_at.isoformat()}",
    ]
    if view.resolved_at is not None:
        lines.append(f"Resolved: {view.resolved_at.isoformat()}")
    return "\n".join(lines)


def chat_text(view: EventView) -> str:
    """The text of a Slack or Telegram message."""
    return f"{SEVERITY_WORD[view.severity]}: {event_sentence(view)}. {_rule_sentence(view)}."


def generic_json(view: EventView) -> dict[str, Any]:
    return {
        "version": 1,
        "event": view.kind,
        "text": chat_text(view),
        "alert": {
            "id": str(view.alert_id),
            "severity": view.severity,
            "rule_name": view.rule_name,
            "metric": view.metric,
            "comparison": view.comparison,
            "threshold": view.threshold,
            "duration_seconds": view.duration_seconds,
            "instance": view.instance,
            "value": view.shown_value,
            "fired_at": view.fired_at.isoformat(),
            "resolved_at": view.resolved_at.isoformat() if view.resolved_at else None,
            "end_reason": view.end_reason,
        },
        "server": {"id": str(view.server_id), "name": view.server_name, "group": view.group_name},
    }
