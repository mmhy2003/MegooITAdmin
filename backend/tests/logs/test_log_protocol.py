import uuid

import pytest
from pydantic import ValidationError

from app.logs.protocol import (
    ON_SOURCE,
    REQUESTS,
    TO_VIEWER,
    WORKER,
    Alive,
    Ended,
    Lines,
    Opened,
    OpenRequest,
    Refused,
    Skipped,
    encode,
    source_channel,
    viewer_channel,
)
from app.logs.sources import JournalSource

HEX = "0123456789abcdef0123456789abcdef"
LINE = {"seq": 1, "time": "2026-11-27T12:00:00Z", "text": "hello"}


def test_the_channel_names():
    assert REQUESTS == "logs:requests"
    assert WORKER == "logs:worker"
    assert viewer_channel(HEX) == f"logs:viewer:{HEX}"
    assert source_channel(HEX) == f"logs:source:{HEX}"


def test_an_open_request_goes_round_trip():
    source = JournalSource(kind="journal", server_id=uuid.uuid4(), unit="ssh.service")
    request = OpenRequest(type="open", socket_id=HEX, request_id=HEX, source=source)

    assert OpenRequest.model_validate_json(encode(request)) == request


def test_the_messages_to_a_viewer_go_round_trip():
    for message in (
        Opened(type="opened", request_id=HEX, key=HEX, run_id=HEX, lines=[LINE], last_seq=1),
        Refused(type="refused", request_id=HEX, key=HEX, reason="not_allowed"),
    ):
        assert TO_VIEWER.validate_json(encode(message)) == message


def test_the_messages_on_a_source_go_round_trip():
    for message in (
        Lines(type="lines", lines=[LINE]),
        Skipped(type="skipped", count=3, after_seq=1),
        Ended(type="ended", reason="exited", status=1),
        Ended(type="ended", reason="idle"),
    ):
        assert ON_SOURCE.validate_json(encode(message)) == message


def test_alive_goes_round_trip():
    alive = Alive(type="alive", run_id=HEX)

    assert Alive.model_validate_json(encode(alive)) == alive


def test_an_open_request_refuses_a_socket_id_that_is_not_32_hex():
    source = JournalSource(kind="journal", server_id=uuid.uuid4())
    for socket_id in ("abc", HEX.upper(), HEX + "0", HEX[:-1] + "g"):
        with pytest.raises(ValidationError):
            OpenRequest(type="open", socket_id=socket_id, request_id=HEX, source=source)


def test_on_source_refuses_an_unknown_type():
    with pytest.raises(ValidationError):
        ON_SOURCE.validate_json('{"type": "opened", "lines": []}')
