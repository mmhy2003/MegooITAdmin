"""The alerts as the collector keeps them: the engine in memory, and each transition written as an alerts row, an
alert_events row and its audit event in one transaction. A write the database refused waits, in order and with its real
times, until the next poll."""

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.actions import alert_event
from app.alerts.models import Alert, AlertEvent, AlertRule
from app.audit import AuditChainBusy, record
from app.collector.alerts.engine import Engine, Firing, Rule, ServerInfo, Transition
from app.collector.state import StatusBook
from app.collector.supervisor import refusal_of
from app.collector.throttle import Throttle
from app.inventory.models import Server
from app.metrics.samples import Sample

logger = logging.getLogger(__name__)

# How often the newest and the worst value of a firing alert are written.
VALUES_EVERY = timedelta(minutes=1)
# A duplicate firing row, or a server or rule removed since: the write can never succeed.
DROPPED = {"23505", "23503"}


class AlertBook:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        engine: Engine | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions, self.clock = sessions, clock
        self.engine = engine if engine is not None else Engine()
        self._pending: list[Transition] = []
        # The last_value and peak_value written for each firing alert, and when.
        self._written: dict[uuid.UUID, tuple[float | None, float | None, datetime]] = {}
        self._warn = Throttle()

    @property
    def pending(self) -> int:
        return len(self._pending)

    async def load(self) -> None:
        """Hands the firing alerts to the engine, so they resolve after a restart. Raises on a database error."""
        async with self.sessions() as session:
            rows = (await session.scalars(select(Alert).where(Alert.state == "firing"))).all()
        now = self.clock()
        self.engine.load_firing(_firing_of(row) for row in rows)
        self._written = {row.id: (row.last_value, row.peak_value, now) for row in rows}

    async def observe(self, sample: Sample, cores: int) -> None:
        """Checks the sample against the rules and writes what changed. Never raises."""
        try:
            await self._write_all(self.engine.observe(sample.server_id, sample.readings, cores, sample.time))
        except Exception:
            logger.exception("Could not check a sample against the alert rules")

    async def poll(self, servers: Sequence[Server], status: StatusBook) -> None:
        """Reads the rules, ends the alerts of rules and servers that changed, fires the unreachable rules, writes the
        firing values due, then retries what was refused. Raises on a database error while reading the rules."""
        async with self.sessions() as session:
            rows = (await session.scalars(select(AlertRule))).all()
        now = self.clock()
        monitored = {
            server.id
            for server in servers
            if refusal_of(server) is None and (status.known(server.id) or (None,))[0] != "not_monitored"
        }
        infos = [ServerInfo(server.id, server.server_group_id, server.name) for server in servers]
        transitions = self.engine.set_servers(infos, monitored, now)
        transitions += self.engine.set_rules((_rule_of(row) for row in rows), now)
        for server in servers:
            known = status.known(server.id)
            since = status.since(server.id)
            if known is not None and known[0] == "unreachable" and since is not None:
                transitions += self.engine.unreachable(server.id, since, now)
        await self._write_all(transitions)
        await self._write_values(now)
        await self._retry()

    async def _write_all(self, transitions: Sequence[Transition]) -> None:
        for transition in transitions:
            if self._pending:
                # Behind what waits: a resolve never goes in before its fire.
                self._pending.append(transition)
            elif not await self._write(transition):
                self._pending.append(transition)

    async def _retry(self) -> None:
        while self._pending:
            if not await self._write(self._pending[0]):
                return
            self._pending.pop(0)

    async def _write(self, transition: Transition) -> bool:
        """One transition in one transaction, the audit event last. False when the database refused it for now;
        True when it is written, or dropped because it never can be."""
        try:
            async with self.sessions() as session:
                if not await self._change_alert(session, transition):
                    return True  # no longer firing in the database: nothing to resolve or end
                await session.execute(
                    insert(AlertEvent).values(
                        id=uuid.uuid4(),
                        alert_id=transition.alert_id,
                        kind=transition.kind,
                        at=transition.at,
                        dispatched_at=None,
                    )
                )
                await record(session, alert_event(transition))
                await session.commit()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) in DROPPED:
                logger.info("Dropped an alert %s the database cannot take", transition.kind)
                return True
            self._keep_pending(exc)
            return False
        except (SQLAlchemyError, OSError, AuditChainBusy) as exc:
            self._keep_pending(exc)
            return False
        firing = transition.firing
        if transition.kind == "fired":
            self._written[transition.alert_id] = (firing.last_value, firing.peak_value, self.clock())
        else:
            self._written.pop(transition.alert_id, None)
        return True

    async def _change_alert(self, session: AsyncSession, transition: Transition) -> bool:
        firing = transition.firing
        if transition.kind == "fired":
            metric, comparison, threshold, duration_seconds, severity = firing.snapshot
            await session.execute(
                insert(Alert).values(
                    id=transition.alert_id,
                    server_id=transition.server.id,
                    rule_id=firing.rule_id,
                    rule_name=firing.rule_name,
                    metric=metric,
                    comparison=comparison,
                    threshold=threshold,
                    duration_seconds=duration_seconds,
                    severity=severity,
                    instance=transition.instance,
                    state="firing",
                    end_reason=None,
                    fired_at=firing.fired_at,
                    resolved_at=None,
                    value=firing.value,
                    last_value=firing.last_value,
                    peak_value=firing.peak_value,
                )
            )
            return True
        closed = await session.execute(
            update(Alert)
            .where(Alert.id == transition.alert_id, Alert.state == "firing")
            .values(
                state=transition.kind,
                resolved_at=transition.at,
                end_reason=transition.end_reason,
                last_value=firing.last_value,
                peak_value=firing.peak_value,
            )
        )
        return closed.rowcount == 1

    async def _write_values(self, now: datetime) -> None:
        """The newest and the worst value of each firing alert, at most once a minute. Not audited: no transition."""
        firing = {alert.alert_id: alert for alert in self.engine.firing()}
        self._written = {alert_id: written for alert_id, written in self._written.items() if alert_id in firing}
        for alert_id, (last_value, peak_value, at) in list(self._written.items()):
            alert = firing[alert_id]
            if (alert.last_value, alert.peak_value) == (last_value, peak_value) or now - at < VALUES_EVERY:
                continue
            values = update(Alert).where(Alert.id == alert_id, Alert.state == "firing")
            try:
                async with self.sessions() as session:
                    await session.execute(values.values(last_value=alert.last_value, peak_value=alert.peak_value))
                    await session.commit()
            except (SQLAlchemyError, OSError) as exc:
                self._keep_pending(exc)
                return
            self._written[alert_id] = (alert.last_value, alert.peak_value, now)

    def _keep_pending(self, exc: Exception) -> None:
        if self._warn():
            logger.warning("Could not write alerts, will retry: %s", type(exc).__name__)


def _rule_of(row: AlertRule) -> Rule:
    return Rule(
        id=row.id,
        name=row.name,
        metric=row.metric,
        comparison=row.comparison,
        threshold=row.threshold,
        duration_seconds=row.duration_seconds,
        severity=row.severity,
        server_group_id=row.server_group_id,
        server_id=row.server_id,
        enabled=row.enabled,
        revision=row.revision,
    )


def _firing_of(row: Alert) -> Firing:
    return Firing(
        alert_id=row.id,
        rule_id=row.rule_id,
        server_id=row.server_id,
        instance=row.instance,
        snapshot=(row.metric, row.comparison, row.threshold, row.duration_seconds, row.severity),
        rule_name=row.rule_name,
        fired_at=row.fired_at,
        value=row.value,
        last_value=row.last_value,
        peak_value=row.peak_value,
    )
