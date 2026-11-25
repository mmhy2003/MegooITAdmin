"""The metrics hypertable, one row per value, and its two rollups.

metrics has no foreign key to servers: a cascade could not reach the rollups, and deletes across compressed chunks
are slow. A removed server's samples age out with the retention windows (migration 0008).
The rollups are continuous aggregates, that is views, so they are plain Tables outside Base.metadata: Alembic
neither creates nor compares them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

METRIC_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
METRIC_MAX_LENGTH = 64
INSTANCE_MAX_LENGTH = 255


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        # Every read filters on server, metric and instance, then a time range. A repeated sample hits this key.
        PrimaryKeyConstraint("server_id", "metric", "instance", "time", name="metrics_pkey"),
        CheckConstraint(
            f"metric ~ '{METRIC_PATTERN}' AND char_length(metric) <= {METRIC_MAX_LENGTH}", name="metrics_metric_check"
        ),
        CheckConstraint(f"char_length(instance) <= {INSTANCE_MAX_LENGTH}", name="metrics_instance_check"),
        # PostgreSQL sorts NaN above Infinity, so this refuses NaN and both infinities.
        CheckConstraint("value > '-Infinity'::float8 AND value < 'Infinity'::float8", name="metrics_value_check"),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    metric: Mapped[str] = mapped_column(Text)
    # The device ("cpu3", "/var", "eth0"), empty for a whole-server value.
    instance: Mapped[str] = mapped_column(Text, server_default=text("''"))
    value: Mapped[float] = mapped_column(Double)


_rollups = MetaData()


def _rollup(name: str) -> Table:
    return Table(
        name,
        _rollups,
        Column("bucket", DateTime(timezone=True)),
        Column("server_id", Uuid),
        Column("metric", Text),
        Column("instance", Text),
        Column("avg_value", Double),
        Column("min_value", Double),
        Column("max_value", Double),
        Column("samples", BigInteger),
    )


metrics_1m = _rollup("metrics_1m")
metrics_1h = _rollup("metrics_1h")
