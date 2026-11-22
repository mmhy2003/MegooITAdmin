"""Points the app at the test database before any app module is imported.

`megoocolab-runner services run test -- uv run pytest` starts that database and sets TEST_DATABASE_URL.
"""

import os
from pathlib import Path

import pytest

RUN_TESTS = "megoocolab-runner services run test -- uv run pytest"


def _docker_only(config: pytest.Config) -> bool:
    return config.getoption("markexpr") == "docker"


def pytest_configure(config: pytest.Config) -> None:
    if _docker_only(config):
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit(f"TEST_DATABASE_URL is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to run against {database!r}: the test database name must end in _test.", returncode=2)
    os.environ["DATABASE_URL"] = url
    os.environ["DB_NULL_POOL"] = "true"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # The image set has no test database, so a `-m docker` run collects only the container tests.
    if _docker_only(config) and collection_path.is_file() and collection_path.name != "test_container.py":
        return True
    return None
