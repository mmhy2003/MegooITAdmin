"""The request and response bodies of /api/alert-rules."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.alerts.catalog import COMPARISONS, METRICS, SEVERITIES

RuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Metric = Literal[METRICS]
Comparison = Literal[COMPARISONS]
# Whether the threshold fits the metric is the service's check (bad_threshold), from the catalog.
Threshold = Annotated[float, Field(allow_inf_nan=False)]
Duration = Annotated[int, Field(ge=0, le=86400)]
Severity = Literal[SEVERITIES]


class AlertRuleIn(BaseModel):
    name: RuleName
    metric: Metric
    # Both None for unreachable, both set for the others.
    comparison: Comparison | None = None
    threshold: Threshold | None = None
    duration_seconds: Duration
    severity: Severity
    # At most one: both None means every server.
    server_group_id: UUID | None = None
    server_id: UUID | None = None
    enabled: bool = True


class AlertRulePatch(BaseModel):
    """Only the fields sent change (model_fields_set). None clears the comparison, the threshold and the scope, and
    keeps the others."""

    name: RuleName | None = None
    metric: Metric | None = None
    comparison: Comparison | None = None
    threshold: Threshold | None = None
    duration_seconds: Duration | None = None
    severity: Severity | None = None
    server_group_id: UUID | None = None
    server_id: UUID | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: UUID
    name: str
    metric: str
    comparison: str | None
    threshold: float | None
    duration_seconds: int
    severity: str
    server_group_id: UUID | None
    server_group_name: str | None
    server_id: UUID | None
    server_name: str | None
    enabled: bool
    # Goes up when the condition, the scope or the severity changes.
    revision: int
    suggested_playbook_id: UUID | None
    # How many of its alerts are firing now.
    firing_count: int
    created_at: datetime
    updated_at: datetime
