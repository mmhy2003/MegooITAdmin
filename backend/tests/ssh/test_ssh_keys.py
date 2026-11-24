import os
from pathlib import Path

import asyncssh
import pytest

from app.ssh.keys import KeyFileError, ensure_key, key_path, load_key, public_key


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "ssh" / "id_ed25519"


def test_the_first_call_creates_a_0600_key_and_the_second_keeps_it(path):
    assert ensure_key(path) is True
    first = path.read_bytes()
    assert ensure_key(path) is False
    assert path.read_bytes() == first
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_a_key_readable_by_others_is_refused(path):
    ensure_key(path)
    path.chmod(0o640)
    with pytest.raises(KeyFileError, match="readable by others"):
        ensure_key(path)
    with pytest.raises(KeyFileError, match="readable by others"):
        load_key(path)


def test_a_missing_key_is_named_in_the_error(path):
    with pytest.raises(KeyFileError) as error:
        load_key(path)
    assert str(path) in str(error.value)


def test_the_public_line_parses_back_to_the_same_key(path):
    ensure_key(path)
    line = public_key(path)
    assert line.startswith("ssh-ed25519 ")
    assert line.endswith(" megooitadmin")
    assert asyncssh.import_public_key(line).public_data == load_key(path).public_data


def test_key_path_follows_the_setting():
    assert key_path() == Path(os.environ["SSH_KEY_FILE"])
