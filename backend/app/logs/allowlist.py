"""The log files a group's members may follow: the rules of a pattern and how a path matches one.

A pattern is an absolute path whose segments may hold "*" (any characters) and "?" (one character). A wildcard
never crosses a "/", and the first segment holds none, so no pattern can reach every directory of the server.
"""

import re
from collections.abc import Iterable

from app.logs.sources import PATH_CHARS, check_path

MAX_PATTERNS = 50
STARTER_PATTERNS = ("/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log")
PATTERN = re.compile(rf"/[*?{PATH_CHARS}]{{0,254}}")  # wildcards first: PATH_CHARS ends with "-"
WILDCARDS = {"*": "[^/]*", "?": "[^/]"}


def check_pattern(value: str) -> str:
    """ValueError unless PATTERN matches, every segment is non-empty and not "." or "..", and the first segment
    holds no wildcard ("/*", "/v*r/log" are refused)."""
    if not PATTERN.fullmatch(value):
        raise ValueError("not a pattern")
    check_path(value.replace("*", "x").replace("?", "x"))  # the segment rule of a path, wildcards as plain letters
    if any(wildcard in value[1:].split("/")[0] for wildcard in WILDCARDS):
        raise ValueError("a wildcard in the first segment")
    return value


def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(WILDCARDS.get(char) or re.escape(char) for char in pattern))


def matches(path: str, patterns: Iterable[str]) -> bool:
    """Whether the path matches one pattern. "*" is "[^/]*" and "?" is "[^/]"; every other character is itself
    (re.escape). The whole path must match."""
    return any(_regex(pattern).fullmatch(path) for pattern in patterns)
