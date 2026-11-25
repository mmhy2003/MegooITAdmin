"""One Sample is everything one server reported at one moment: a Reading per value."""

import uuid

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.metrics.models import INSTANCE_MAX_LENGTH, METRIC_MAX_LENGTH, METRIC_PATTERN


class Reading(BaseModel):
    """One value: a metric such as cpu.used_percent, of the whole server (instance "") or of one device."""

    model_config = ConfigDict(frozen=True)

    metric: str = Field(max_length=METRIC_MAX_LENGTH, pattern=METRIC_PATTERN)
    instance: str = Field(default="", max_length=INSTANCE_MAX_LENGTH)
    # Refused like the table's check: one NaN would spoil every average it falls into.
    value: float = Field(allow_inf_nan=False)


class Sample(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: AwareDatetime
    server_id: uuid.UUID
    readings: tuple[Reading, ...]
