"""The audit action names of alerts, which the collector records as they fire, resolve or end, and of the alert rules
the Owner manages."""

from app.audit import Actor, Event, Target
from app.collector.alerts.engine import Transition

ALERT_FIRED = "alert.fired"
ALERT_RESOLVED = "alert.resolved"
ALERT_ENDED = "alert.ended"

ALERT_ACTIONS = frozenset({ALERT_FIRED, ALERT_RESOLVED, ALERT_ENDED})

ALERT_RULE_CREATED = "alert_rule.created"
ALERT_RULE_CHANGED = "alert_rule.changed"
ALERT_RULE_DELETED = "alert_rule.deleted"

RULE_ACTIONS = frozenset({ALERT_RULE_CREATED, ALERT_RULE_CHANGED, ALERT_RULE_DELETED})

_BY_KIND = {"fired": ALERT_FIRED, "resolved": ALERT_RESOLVED, "ended": ALERT_ENDED}
ACTOR = Actor.system("collector")


def alert_event(transition: Transition) -> Event:
    """The audit event of a transition. Numbers go in as text: the audit log refuses floats."""
    firing = transition.firing
    metric, _, threshold, _, severity = firing.snapshot
    value = firing.value if transition.kind == "fired" else firing.last_value
    return Event(
        action=_BY_KIND[transition.kind],
        actor=ACTOR,
        target=Target(type="alert", id=str(transition.alert_id), name=firing.rule_name),
        context={"server_id": str(transition.server.id), "server_group_id": str(transition.server.group_id)},
        result_detail={
            "server": transition.server.name,
            "rule_id": None if firing.rule_id is None else str(firing.rule_id),
            "metric": metric,
            "instance": transition.instance,
            "severity": severity,
            "value": _text(value),
            "threshold": _text(threshold),
            "end_reason": transition.end_reason,
        },
    )


def _text(number: float | None) -> str | None:
    return None if number is None else format(number, ".2f")
