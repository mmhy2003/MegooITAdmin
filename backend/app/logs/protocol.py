"""The messages between the log socket and the logs worker over Valkey pub/sub.

A socket asks on REQUESTS to open a source and gets the worker's answer, with the backlog, on its own viewer
channel. The source's lines, skipped counts and its end go to every viewer on the source's channel. The worker says
it is alive on WORKER. Valkey carries these messages only: no log line is stored there.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.logs.sources import Source

REQUESTS = "logs:requests"
WORKER = "logs:worker"
HEX32 = r"^[0-9a-f]{32}$"
REFUSALS = frozenset({"not_found", "not_allowed", "not_an_ssh_server", "host_key_not_pinned", "host_key_changed",
                      "too_many_sources"})


def viewer_channel(socket_id: str) -> str:
    return f"logs:viewer:{socket_id}"


def source_channel(key: str) -> str:
    return f"logs:source:{key}"


class OpenRequest(BaseModel):
    type: Literal["open"]
    socket_id: str = Field(pattern=HEX32)
    request_id: str = Field(pattern=HEX32)
    source: Source


class Opened(BaseModel):
    type: Literal["opened"]
    request_id: str
    key: str
    run_id: str
    lines: list[dict]
    last_seq: int


class Refused(BaseModel):
    type: Literal["refused"]
    request_id: str
    key: str
    reason: str


class Lines(BaseModel):
    type: Literal["lines"]
    lines: list[dict]


class Skipped(BaseModel):
    type: Literal["skipped"]
    count: int
    after_seq: int


class Ended(BaseModel):
    type: Literal["ended"]
    reason: str
    status: int | None = None


class Alive(BaseModel):
    type: Literal["alive"]
    run_id: str


TO_VIEWER: TypeAdapter[Opened | Refused] = TypeAdapter(Annotated[Opened | Refused, Field(discriminator="type")])
ON_SOURCE: TypeAdapter[Lines | Skipped | Ended] = TypeAdapter(
    Annotated[Lines | Skipped | Ended, Field(discriminator="type")]
)


def encode(message: BaseModel) -> str:
    return message.model_dump_json()
