import re
import uuid

import pytest
from pydantic import ValidationError

from app.logs.sources import (
    FILE_SCRIPT,
    SOURCES,
    ContainerSource,
    FileSource,
    JournalSource,
    command,
    describe,
    source_key,
)

S = uuid.UUID("11111111-2222-3333-4444-555555555555")
JOURNAL_START = [
    "journalctl", "--no-pager", "-f", "-o", "json",
    "--output-fields=MESSAGE,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER", "-n", "200",
]


def test_a_journal_source_runs_journalctl_with_its_filters():
    source = JournalSource(kind="journal", server_id=S, unit="nginx.service", priority="warning", this_boot=True)

    assert command(source) == JOURNAL_START + ["-u", "nginx.service", "-p", "4", "-b"]
    assert command(JournalSource(kind="journal", server_id=S)) == JOURNAL_START


def test_a_file_source_runs_tail_behind_a_read_check():
    assert FILE_SCRIPT == 'test -f "$1" && test -r "$1" || exit 66; exec tail -n 200 -F -- "$1"'
    assert command(FileSource(kind="file", server_id=S, path="/var/log/syslog")) == [
        "sh", "-c", FILE_SCRIPT, "megoo-file", "/var/log/syslog",
    ]


def test_a_container_source_runs_megoo_ctl():
    assert command(ContainerSource(kind="container", server_id=S, container_id="web-1")) == [
        "sudo", "-n", "/usr/local/sbin/megoo-ctl", "docker", "logs", "web-1", "--follow", "--tail", "200",
    ]


@pytest.mark.parametrize("unit", ["", "-x", ".hidden", "a b", "a;b", "x" * 256])
def test_refused_units(unit):
    with pytest.raises(ValidationError, match="unit"):
        SOURCES.validate_python({"kind": "journal", "server_id": str(S), "unit": unit})


@pytest.mark.parametrize("unit", ["getty@tty1.service", "a:b_c.d-e"])
def test_accepted_units(unit):
    assert SOURCES.validate_python({"kind": "journal", "server_id": str(S), "unit": unit}).unit == unit


@pytest.mark.parametrize("path", [
    "var/log/x", "/var/../etc/shadow", "/var/log/./x", "/var//log", "/var/log/", "/var/log/*.log", "/var/log/a b",
    "/var/log/$(x)", "/" + "a" * 255,
])
def test_refused_paths(path):
    with pytest.raises(ValidationError, match="path"):
        SOURCES.validate_python({"kind": "file", "server_id": str(S), "path": path})


@pytest.mark.parametrize("path", ["/var/log/syslog", "/var/log/nginx/access.log", "/" + "a" * 254])
def test_accepted_paths(path):
    assert SOURCES.validate_python({"kind": "file", "server_id": str(S), "path": path}).path == path


@pytest.mark.parametrize("container_id", ["-rm", "a/b", "a b", "x" * 129])
def test_refused_containers(container_id):
    with pytest.raises(ValidationError, match="container"):
        SOURCES.validate_python({"kind": "container", "server_id": str(S), "container_id": container_id})


def test_an_unknown_kind_or_field_is_refused():
    with pytest.raises(ValidationError):
        SOURCES.validate_python({"kind": "podman", "server_id": str(S), "container_id": "web-1"})
    with pytest.raises(ValidationError):
        SOURCES.validate_python({"kind": "file", "server_id": str(S), "path": "/var/log/syslog", "lines": 5})


def test_the_key_is_the_same_for_equal_sources_and_differs_with_a_filter():
    plain = SOURCES.validate_python({"kind": "journal", "server_id": str(S)})
    spelled = SOURCES.validate_python(
        {"kind": "journal", "server_id": str(S), "unit": None, "priority": None, "this_boot": False}
    )
    filtered = SOURCES.validate_python({"kind": "journal", "server_id": str(S), "priority": "warning"})

    assert source_key(plain) == source_key(spelled)
    assert source_key(filtered) != source_key(plain)
    assert re.fullmatch(r"[0-9a-f]{32}", source_key(plain))


def test_describe_holds_every_field():
    assert describe(JournalSource(kind="journal", server_id=S)) == {
        "kind": "journal", "server_id": str(S), "unit": None, "priority": None, "this_boot": False,
    }
    assert describe(FileSource(kind="file", server_id=S, path="/var/log/syslog")) == {
        "kind": "file", "server_id": str(S), "path": "/var/log/syslog",
    }
    assert describe(ContainerSource(kind="container", server_id=S, container_id="web-1")) == {
        "kind": "container", "server_id": str(S), "container_id": "web-1",
    }
