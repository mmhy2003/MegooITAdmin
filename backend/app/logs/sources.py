"""The three log sources a person can follow, the rules on their fields, their key and the command each one runs.

A source is a journal (with optional unit, priority and boot filters), a file, or a Docker container of one server.
Every field that reaches the server's command line is checked here first, so the command never needs a shell to
read it: a unit, a path and a container name are plain words that cannot start an option or hold a quote.
Equal sources share one key, so the viewers of one source share one channel.
"""

import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.ssh.client import CTL

BACKLOG = 200
PRIORITIES = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")  # index = syslog number
Priority = Literal["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.@-]{0,254}")
PATH_CHARS = "A-Za-z0-9._/@%+=:,-"
PATH = re.compile(rf"/[{PATH_CHARS}]{{0,254}}")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")  # megoo-ctl's own rule
JOURNAL_FIELDS = "MESSAGE,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER"
NOT_READABLE = 66
# $1 is the path. A missing or unreadable file exits with NOT_READABLE at once, instead of tail -F waiting for it.
FILE_SCRIPT = f'test -f "$1" && test -r "$1" || exit {NOT_READABLE}; exec tail -n {BACKLOG} -F -- "$1"'


def check_path(value: str) -> str:
    """The path when it is absolute, of allowed characters, and every segment is non-empty and not "." or "..";
    ValueError otherwise."""
    if not PATH.fullmatch(value) or any(part in ("", ".", "..") for part in value[1:].split("/")):
        raise ValueError("not a path")
    return value


class _Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: UUID


class JournalSource(_Source):
    kind: Literal["journal"]
    unit: str | None = None
    priority: Priority | None = None
    this_boot: bool = False

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str | None) -> str | None:
        if value is not None and not UNIT.fullmatch(value):
            raise ValueError("not a unit")
        return value


class FileSource(_Source):
    kind: Literal["file"]
    path: str

    _path = field_validator("path")(check_path)


class ContainerSource(_Source):
    kind: Literal["container"]
    container_id: str

    @field_validator("container_id")
    @classmethod
    def _container_id(cls, value: str) -> str:
        if not CONTAINER.fullmatch(value):
            raise ValueError("not a container")
        return value


Source = Annotated[JournalSource | FileSource | ContainerSource, Field(discriminator="kind")]
SOURCES: TypeAdapter[Source] = TypeAdapter(Source)


def describe(source: Source) -> dict:
    """Every field of the source, defaults included, as JSON values."""
    return source.model_dump(mode="json")


def source_key(source: Source) -> str:
    """32 hex characters, the same for equal sources however their defaults were given."""
    text = json.dumps(describe(source), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def command(source: Source) -> list[str]:
    """The argv the server runs to follow the source, starting with its last BACKLOG lines."""
    match source:
        case JournalSource():
            argv = ["journalctl", "--no-pager", "-f", "-o", "json", f"--output-fields={JOURNAL_FIELDS}",
                    "-n", str(BACKLOG)]
            if source.unit is not None:
                argv += ["-u", source.unit]
            if source.priority is not None:
                argv += ["-p", str(PRIORITIES.index(source.priority))]
            if source.this_boot:
                argv.append("-b")
            return argv
        case FileSource():
            return ["sh", "-c", FILE_SCRIPT, "megoo-file", source.path]
        case ContainerSource():
            return ["sudo", "-n", CTL, "docker", "logs", source.container_id, "--follow", "--tail", str(BACKLOG)]
