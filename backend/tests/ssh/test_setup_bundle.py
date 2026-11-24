import subprocess

from app.ssh.setup import SCRIPT, ctl_version, script_text


def test_the_bundled_script_is_the_file_next_to_the_module():
    assert script_text().startswith("#!/bin/sh\n")
    assert script_text() == SCRIPT.read_text()


def test_the_script_installs_megoo_ctl_version_1():
    assert ctl_version() == 1


def test_the_script_is_valid_sh():
    assert subprocess.run(["sh", "-n", str(SCRIPT)]).returncode == 0
