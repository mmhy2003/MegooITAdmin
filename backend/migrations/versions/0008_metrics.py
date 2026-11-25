"""metrics: the metrics hypertable, one row per value, its 1-minute and 1-hour rollups, and their policies

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEGMENT_BY = "server_id, metric, instance"


def _set_rollup_chunk_interval(view: str, interval: str) -> None:
    # A rollup keeps its rows in a materialization hypertable of its own: the chunk interval is set there.
    op.execute(
        "SELECT set_chunk_time_interval("
        "(quote_ident(materialization_hypertable_schema) || '.' || quote_ident(materialization_hypertable_name))::regclass,"
        f" INTERVAL '{interval}') FROM timescaledb_information.continuous_aggregates WHERE view_name = '{view}'"
    )


def upgrade() -> None:
    op.create_table(
        "metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.CheckConstraint(
            r"metric ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$' AND char_length(metric) <= 64", name="metrics_metric_check"
        ),
        sa.CheckConstraint("char_length(instance) <= 255", name="metrics_instance_check"),
        sa.CheckConstraint("value > '-Infinity'::float8 AND value < 'Infinity'::float8", name="metrics_value_check"),
        sa.PrimaryKeyConstraint("server_id", "metric", "instance", "time", name="metrics_pkey"),
    )
    # create_default_indexes => false: the primary key is the index every read uses.
    op.execute(
        "SELECT create_hypertable('metrics', by_range('time', INTERVAL '6 hours'), create_default_indexes => false)"
    )
    op.execute(
        "ALTER TABLE metrics SET (timescaledb.compress, "
        f"timescaledb.compress_segmentby = '{SEGMENT_BY}', timescaledb.compress_orderby = 'time DESC')"
    )

    # Real-time (materialized_only = false): a query sees the current minute without waiting for a refresh.
    op.execute(
        """
        CREATE MATERIALIZED VIEW metrics_1m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 minute', time) AS bucket, server_id, metric, instance,
               avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value, count(*) AS samples
        FROM metrics
        GROUP BY time_bucket(INTERVAL '1 minute', time), server_id, metric, instance
        WITH NO DATA
        """
    )
    _set_rollup_chunk_interval("metrics_1m", "1 day")

    # Built on metrics_1m, kept 30 days, so it can catch up after a long stop; raw samples are gone after 48 hours.
    # The average is weighted by each minute's sample count, so it equals the average of the raw values.
    op.execute(
        """
        CREATE MATERIALIZED VIEW metrics_1h
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 hour', bucket) AS bucket, server_id, metric, instance,
               sum(avg_value * samples) / sum(samples) AS avg_value, min(min_value) AS min_value,
               max(max_value) AS max_value, sum(samples)::bigint AS samples
        FROM metrics_1m
        GROUP BY time_bucket(INTERVAL '1 hour', bucket), server_id, metric, instance
        WITH NO DATA
        """
    )
    _set_rollup_chunk_interval("metrics_1h", "30 days")

    for view in ("metrics_1m", "metrics_1h"):
        op.execute(
            f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.compress = true, "
            f"timescaledb.compress_segmentby = '{SEGMENT_BY}', timescaledb.compress_orderby = 'bucket DESC')"
        )

    # Each refresh window is shorter than its source's retention and ends before its own compression starts.
    op.execute(
        "SELECT add_continuous_aggregate_policy('metrics_1m', start_offset => INTERVAL '24 hours',"
        " end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute')"
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy('metrics_1h', start_offset => INTERVAL '7 days',"
        " end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour')"
    )
    op.execute("SELECT add_compression_policy('metrics', compress_after => INTERVAL '1 hour')")
    op.execute("SELECT add_compression_policy('metrics_1m', compress_after => INTERVAL '2 days')")
    op.execute("SELECT add_compression_policy('metrics_1h', compress_after => INTERVAL '30 days')")
    # Retention drops whole chunks: data is kept at least the stated time and at most one chunk longer.
    op.execute(
        "SELECT add_retention_policy('metrics', drop_after => INTERVAL '48 hours', schedule_interval => INTERVAL '1 hour')"
    )
    op.execute("SELECT add_retention_policy('metrics_1m', drop_after => INTERVAL '30 days')")
    op.execute("SELECT add_retention_policy('metrics_1h', drop_after => INTERVAL '13 months')")

    # The backend only reads. The collector's role and its INSERT grant come with the collector (MITA-26).
    op.execute("GRANT SELECT ON metrics, metrics_1m, metrics_1h TO megooitadmin_api")


def downgrade() -> None:
    # Policies and grants go with their relations.
    op.execute("DROP MATERIALIZED VIEW metrics_1h")
    op.execute("DROP MATERIALIZED VIEW metrics_1m")
    op.drop_table("metrics")
