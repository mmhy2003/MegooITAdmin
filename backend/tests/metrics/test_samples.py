import math
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


@pytest.mark.parametrize("metric", ["cpu.used_percent", "load1", "disk.used_percent", "net.rx_bytes"])
def test_a_lowercase_dotted_name_is_accepted(metric):
    assert Reading(metric=metric, value=1.0).instance == ""


@pytest.mark.parametrize("metric", ["", "CPU", "1cpu", "cpu..used", "cpu.", ".cpu", "cpu-used", "a" * 65])
def test_a_metric_name_outside_the_pattern_is_refused(metric):
    with pytest.raises(ValidationError):
        Reading(metric=metric, value=1.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_value_that_is_not_finite_is_refused(value):
    with pytest.raises(ValidationError):
        Reading(metric="cpu.used_percent", value=value)


def test_an_instance_longer_than_255_characters_is_refused():
    assert Reading(metric="disk.used_percent", instance="/" * 255, value=1.0)
    with pytest.raises(ValidationError):
        Reading(metric="disk.used_percent", instance="/" * 256, value=1.0)


def test_a_sample_needs_an_aware_time():
    with pytest.raises(ValidationError):
        Sample(time=datetime(2026, 11, 25, 10, 0), server_id=uuid.uuid4(), readings=())
    sample = Sample(time=NOW, server_id=uuid.uuid4(), readings=[Reading(metric="load1", value=0.5)])
    assert sample.readings == (Reading(metric="load1", value=0.5),)
