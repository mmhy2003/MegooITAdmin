"""The setup script an admin runs on each server (megoo-setup.sh, bundled with the backend), and the version of the
megoo-ctl it installs: the script is the only place that version is written."""

import re
from functools import cache
from pathlib import Path

SCRIPT = Path(__file__).with_name("megoo-setup.sh")


@cache
def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@cache
def ctl_version() -> int:
    match = re.search(r"^CTL_VERSION=(\d+)$", script_text(), re.MULTILINE)
    if match is None:
        raise RuntimeError(f"{SCRIPT} sets no CTL_VERSION")
    return int(match.group(1))
