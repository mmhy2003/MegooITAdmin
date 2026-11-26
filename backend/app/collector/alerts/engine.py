"""The alert engine: rules, servers and samples in, transitions out. It is pure: no I/O and no clock of its own, every
time comes with the call.

A rule's condition must hold for its whole duration before the alert fires. Each alert is keyed by (rule, server,
instance): instance "" for a whole-server metric, the mount point for a filesystem."""

import dataclasses
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.alerts.catalog import CATALOG
from app.metrics.samples import Reading

# Seconds between two samples of a server after which its counting starts again: the samples in between are missing.
GAP = 30.0

type Key = tuple[uuid.UUID, uuid.UUID, str]  # (rule_id, server_id, instance)


@dataclass(frozen=True)
class ServerInfo:
    id: uuid.UUID
    group_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class Rule:
    id: uuid.UUID
    name: str
    metric: str
    comparison: str | None
    threshold: float | None
    duration_seconds: int
    severity: str
    server_group_id: uuid.UUID | None
    server_id: uuid.UUID | None
    enabled: bool
    revision: int

    def applies_to(self, server: ServerInfo) -> bool:
        if self.server_id is not None:
            return server.id == self.server_id
        if self.server_group_id is not None:
            return server.group_id == self.server_group_id
        return True

    def snapshot(self) -> tuple:
        """What a firing alert copies from its rule: a change to any of it ends the alert."""
        return (self.metric, self.comparison, self.threshold, self.duration_seconds, self.severity)


@dataclass
class Firing:
    alert_id: uuid.UUID
    rule_id: uuid.UUID | None
    server_id: uuid.UUID
    instance: str
    snapshot: tuple
    rule_name: str
    fired_at: datetime
    value: float | None
    last_value: float | None
    peak_value: float | None


@dataclass(frozen=True)
class Transition:
    kind: Literal["fired", "resolved", "ended"]
    alert_id: uuid.UUID
    server: ServerInfo
    instance: str
    at: datetime
    rule: Rule | None  # set for "fired" (the snapshot is copied from it)
    firing: Firing  # the alert as it is after the transition
    end_reason: str | None = None


class Engine:
    def __init__(self) -> None:
        self._servers: dict[uuid.UUID, ServerInfo] = {}
        self._rules: list[Rule] = []
        self._counting: dict[Key, tuple[int, datetime]] = {}  # (rule revision, when the condition started to hold)
        self._firing: dict[Key, Firing] = {}
        self._last_sample: dict[uuid.UUID, datetime] = {}

    def load_firing(self, firing: Iterable[Firing]) -> None:
        """The alerts still firing in the database, at start: they resolve and end like the engine's own."""
        for alert in firing:
            self._firing[_key_of(alert)] = alert

    def set_servers(
        self, servers: Iterable[ServerInfo], monitored: Collection[uuid.UUID], at: datetime
    ) -> list[Transition]:
        """Forgets the servers that are gone, with their alerts (the database removes the rows with the server), and
        ends the alerts of the servers that are not monitored."""
        self._servers = {server.id: server for server in servers}
        self._firing = {key: firing for key, firing in self._firing.items() if key[1] in self._servers}
        self._last_sample = {sid: last for sid, last in self._last_sample.items() if sid in self._servers}

        resting = {sid for sid in self._servers if sid not in monitored}
        self._counting = {
            key: value for key, value in self._counting.items() if key[1] in self._servers and key[1] not in resting
        }
        return [self._end(key, "server_not_monitored", at) for key in list(self._firing) if key[1] in resting]

    def set_rules(self, rules: Iterable[Rule], at: datetime) -> list[Transition]:
        """Ends the alerts whose rule is gone, switched off or changed. A rename changes nothing: the next fires carry
        the new name."""
        self._rules = list(rules)
        by_id = {rule.id: rule for rule in self._rules}
        self._counting = {key: value for key, value in self._counting.items() if self._still_counts(by_id, key, value)}
        transitions: list[Transition] = []
        for key, firing in list(self._firing.items()):
            server = self._servers.get(firing.server_id)
            if server is None:
                continue  # set_servers forgets it
            rule = by_id.get(firing.rule_id) if firing.rule_id is not None else None
            if rule is None:
                transitions.append(self._end(key, "rule_deleted", at))
            elif not rule.enabled:
                transitions.append(self._end(key, "rule_disabled", at))
            elif rule.snapshot() != firing.snapshot or not rule.applies_to(server):
                transitions.append(self._end(key, "rule_changed", at))
        return transitions

    def observe(self, server_id: uuid.UUID, readings: Sequence[Reading], cores: int, at: datetime) -> list[Transition]:
        server = self._servers.get(server_id)
        if server is None:
            return []
        previous = self._last_sample.get(server_id)
        self._last_sample[server_id] = at
        if previous is not None and (at - previous).total_seconds() > GAP:
            self._counting = {key: value for key, value in self._counting.items() if key[1] != server_id}

        # A sample says the server is back: its unreachable alerts resolve, with no value.
        transitions = [
            self._resolve(key, server, at)
            for key, firing in list(self._firing.items())
            if key[1] == server_id and firing.snapshot[0] == "unreachable"
        ]
        for rule in self._rules:
            if not rule.enabled or rule.metric == "unreachable" or not rule.applies_to(server):
                continue
            spec = CATALOG[rule.metric]
            if spec.per_instance:
                values = {r.instance: r.value for r in readings if r.metric == rule.metric}
                transitions += self._vanished(rule, server, values.keys(), at)
            else:
                whole = [r.value for r in readings if r.metric == rule.metric and r.instance == ""]
                if not whole:
                    continue
                values = {"": whole[0] / max(cores, 1) if spec.per_core else whole[0]}
            for instance, value in values.items():
                transitions += self._check(rule, server, instance, value, at)
        return transitions

    def unreachable(self, server_id: uuid.UUID, since: datetime, at: datetime) -> list[Transition]:
        """The server has been unreachable since `since`: each unreachable rule fires once its duration has passed."""
        server = self._servers.get(server_id)
        if server is None:
            return []
        transitions: list[Transition] = []
        for rule in self._rules:
            if not rule.enabled or rule.metric != "unreachable" or not rule.applies_to(server):
                continue
            key = (rule.id, server.id, "")
            if key in self._firing or (at - since).total_seconds() < rule.duration_seconds:
                continue
            transitions.append(self._fire(key, rule, server, None, at))
        return transitions

    def firing(self) -> list[Firing]:
        return list(self._firing.values())

    def _check(self, rule: Rule, server: ServerInfo, instance: str, value: float, at: datetime) -> list[Transition]:
        key = (rule.id, server.id, instance)
        holds = value > rule.threshold if rule.comparison == "above" else value < rule.threshold
        firing = self._firing.get(key)
        if not holds:
            self._counting.pop(key, None)
            if firing is None:
                return []
            firing.last_value = value
            return [self._resolve(key, server, at)]
        if firing is not None:
            firing.last_value = value
            peak = max if rule.comparison == "above" else min
            firing.peak_value = peak(firing.peak_value, value)
            return []
        counting = self._counting.get(key)
        if counting is None or counting[0] != rule.revision:
            counting = self._counting[key] = (rule.revision, at)
        if (at - counting[1]).total_seconds() < rule.duration_seconds:
            return []
        del self._counting[key]
        return [self._fire(key, rule, server, value, at)]

    def _fire(self, key: Key, rule: Rule, server: ServerInfo, value: float | None, at: datetime) -> Transition:
        firing = self._firing[key] = Firing(
            alert_id=uuid.uuid4(),
            rule_id=rule.id,
            server_id=server.id,
            instance=key[2],
            snapshot=rule.snapshot(),
            rule_name=rule.name,
            fired_at=at,
            value=value,
            last_value=value,
            peak_value=value,
        )
        # A copy: the engine's own Firing goes on changing with later samples.
        return Transition("fired", firing.alert_id, server, key[2], at, rule, dataclasses.replace(firing))

    def _vanished(self, rule: Rule, server: ServerInfo, present: Collection[str], at: datetime) -> list[Transition]:
        """A filesystem missing from the sample stops counting, and its firing alert resolves with its values kept."""
        gone = [key for key in self._counting if key[:2] == (rule.id, server.id) and key[2] not in present]
        for key in gone:
            del self._counting[key]
        return [
            self._resolve(key, server, at)
            for key in list(self._firing)
            if key[:2] == (rule.id, server.id) and key[2] not in present
        ]

    def _resolve(self, key: Key, server: ServerInfo, at: datetime) -> Transition:
        firing = self._firing.pop(key)
        return Transition("resolved", firing.alert_id, server, firing.instance, at, None, firing)

    def _still_counts(self, by_id: dict[uuid.UUID, Rule], key: Key, value: tuple[int, datetime]) -> bool:
        """A count goes on only while its rule, at the same revision, is enabled and applies to the server: a rule
        switched off and on again, or a server moved out of its scope and back, holds for the full duration again."""
        rule = by_id.get(key[0])
        server = self._servers.get(key[1])
        return (
            rule is not None
            and server is not None
            and rule.enabled
            and rule.revision == value[0]
            and rule.applies_to(server)
        )

    def _end(self, key: Key, reason: str, at: datetime) -> Transition:
        firing = self._firing.pop(key)
        server = self._servers[firing.server_id]
        return Transition("ended", firing.alert_id, server, firing.instance, at, None, firing, reason)


def _key_of(firing: Firing) -> Key:
    """A loaded alert whose rule was deleted has no rule_id: its own id stands in, so that two of them on the same
    server and instance stay apart. It never matches a rule, and set_rules ends it."""
    return (firing.rule_id if firing.rule_id is not None else firing.alert_id, firing.server_id, firing.instance)
