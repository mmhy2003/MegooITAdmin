import ipaddress
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.audit import GENESIS, canonical, event_hash
from app.audit.chain import document, time_text

TIME = datetime(2026, 11, 23, 7, 45, 31, 362000, tzinfo=UTC)

KNOWN_COLUMNS = {
    "action": "server.created",
    "actor_type": "human",
    "actor_id": "7",
    "actor_name": "Zoë",
    "actor_details": {},
    "context": {},
    "result": "success",
    "source_ip": "203.0.113.9",
    "reason": None,
}

KNOWN_CANONICAL = (
    '{"action":"server.created","actor_details":{},"actor_id":"7","actor_name":"Zoë","actor_type":"human",'
    '"context":{},"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"result":"success","seq":1,"source_ip":"203.0.113.9","time":"2026-11-23T07:45:31.362Z"}'
).encode()

KNOWN_HASH = "845f986617bdb34bfc2e2fc97ed0ea98d72bb0c6afcf5d4a0a9663fe122b20a2"


def test_canonical_sorts_keys_without_spaces():
    assert canonical({"b": 1, "a": {"d": [1, 2], "c": "x"}}) == b'{"a":{"c":"x","d":[1,2]},"b":1}'


def test_document_leaves_out_null_columns_but_keeps_nested_nulls():
    doc = document(1, TIME, GENESIS, {"reason": None, "change": {"name": {"before": None, "after": "db-01"}}})

    assert "reason" not in doc
    assert doc["change"] == {"name": {"before": None, "after": "db-01"}}


def test_canonical_keeps_non_ascii_text_as_utf8():
    data = canonical({"actor_name": "Zoë"})

    assert b"Zo\xc3\xab" in data
    assert b"\\u00eb" not in data


def test_time_is_utc_with_milliseconds():
    time = datetime(2026, 11, 23, 9, 45, 31, 362999, tzinfo=timezone(timedelta(hours=2)))

    assert time_text(time) == "2026-11-23T07:45:31.362Z"


def test_source_ip_has_one_text_form():
    as_address = document(1, TIME, GENESIS, {"source_ip": ipaddress.ip_address("203.0.113.9")})
    as_text = document(1, TIME, GENESIS, {"source_ip": "203.0.113.9"})

    assert as_address == as_text
    assert as_text["source_ip"] == "203.0.113.9"


def test_a_fixed_event_has_a_fixed_hash():
    assert canonical(document(1, TIME, GENESIS, KNOWN_COLUMNS)) == KNOWN_CANONICAL
    assert event_hash(1, TIME, GENESIS, KNOWN_COLUMNS).hex() == KNOWN_HASH


def test_a_float_is_refused():
    with pytest.raises(ValueError):
        canonical({"change": {"load": 0.5}})


def test_genesis_is_32_zero_bytes():
    assert GENESIS == b"\x00" * 32
