from pathlib import Path

import pytest

from app.ssh.cli import main


@pytest.fixture
def path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "k" / "id_ed25519"
    monkeypatch.setattr("app.ssh.keys.key_path", lambda: path)
    return path


def test_ensure_key_makes_the_key_once(path, capsys):
    assert main(["ensure-key"]) == 0
    assert "Created the platform's SSH key in" in capsys.readouterr().out
    assert main(["ensure-key"]) == 0
    assert "The platform's SSH key is in" in capsys.readouterr().out


def test_public_key_prints_one_ed25519_line(path, capsys):
    main(["ensure-key"])
    capsys.readouterr()
    assert main(["public-key"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("ssh-ed25519 ")


def test_ensure_key_refuses_a_key_readable_by_others(path, capsys):
    path.parent.mkdir()
    path.write_text("not a key")
    path.chmod(0o644)
    assert main(["ensure-key"]) == 1
    assert "readable by others" in capsys.readouterr().err


def test_public_key_without_a_key_names_it_missing(path, capsys):
    assert main(["public-key"]) == 1
    assert "is missing" in capsys.readouterr().err
