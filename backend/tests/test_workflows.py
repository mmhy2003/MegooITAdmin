"""The GitHub Actions workflows run only on GitHub, so their text is checked here: the triggers, the permissions
and the command of each job. They need neither Docker nor a database."""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
INSTALL = "https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh"
INSTALL_STEP = "Install megoocolab-runner"

# Each job: its working directory (None for the repository root) and the commands it runs, in order.
JOBS = {
    "backend": ("backend", ["megoocolab-runner services run test -- uv run pytest"]),
    "security": (None, ["make test-security"]),
    "frontend": ("frontend", ["npm ci", "npx tsc --noEmit", "npm run lint", "npm test", "npm run build"]),
    "release-tools": (None, ["uv run --project backend pytest tools/release", "python tools/release/versions.py check"]),
    "backend-image": ("backend", ["megoocolab-runner services run image -- uv run pytest -m docker"]),
    "frontend-image": ("frontend", ["npm ci", "megoocolab-runner services run web -- npm run test:image"]),
    "stack": ("backend", ["megoocolab-runner services run stack -- uv run pytest -m stack"]),
}


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def runs(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def needs_runner(job: dict) -> bool:
    return any("megoocolab-runner services run" in line or "make test-security" in line for line in runs(job))


@pytest.fixture
def ci() -> dict:
    return workflow("ci.yml")


def test_ci_runs_on_develop_and_for_the_release(ci):
    # PyYAML reads the key `on` as True: it is a boolean in YAML 1.1.
    on = ci[True]
    assert set(on) == {"push", "pull_request", "workflow_call"}
    assert on["push"] == {"branches": ["develop"]}
    assert on["pull_request"] == {"branches": ["develop"]}
    assert on["workflow_call"] is None
    assert ci["permissions"] == {"contents": "read"}


def test_ci_has_one_job_per_check(ci):
    assert set(ci["jobs"]) == set(JOBS)
    for name, job in ci["jobs"].items():
        assert "needs" not in job, f"{name} waits for another job"


@pytest.mark.parametrize("name", JOBS)
def test_each_job_runs_its_commands_in_its_directory(ci, name):
    job = ci["jobs"][name]
    directory, commands = JOBS[name]
    assert job.get("defaults", {}).get("run", {}).get("working-directory") == directory
    lines = runs(job)
    positions = []
    for command in commands:
        found = [i for i, line in enumerate(lines) if command in line]
        assert found, f"{name} does not run {command}"
        positions.append(found[0])
    assert positions == sorted(positions), f"{name} runs its commands out of order"


@pytest.mark.parametrize("name", JOBS)
def test_each_job_runs_on_ubuntu_with_a_timeout_and_a_read_only_checkout(ci, name):
    job = ci["jobs"][name]
    assert job["runs-on"] == "ubuntu-24.04"
    assert 0 < job["timeout-minutes"] <= 30
    first = job["steps"][0]
    assert first["uses"].startswith("actions/checkout@")
    assert first["with"]["persist-credentials"] is False


def test_the_runner_version_is_pinned_once(ci):
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(ci["env"]["MEGOO_RUNNER_VERSION"]))
    assert str(ci["env"]["UV_LOCKED"]) == "1"


@pytest.mark.parametrize("name", JOBS)
def test_every_job_that_starts_services_installs_the_pinned_runner_first(ci, name):
    job = ci["jobs"][name]
    names = [step.get("name") for step in job["steps"]]
    if not needs_runner(job):
        assert INSTALL_STEP not in names
        return
    install = job["steps"][names.index(INSTALL_STEP)]
    assert INSTALL in install["run"]
    assert 'MEGOO_RUNNER_VERSION="$MEGOO_RUNNER_VERSION" sh -s -- --system' in install["run"]
    first_use = next(i for i, step in enumerate(job["steps"]) if "run" in step and needs_runner({"steps": [step]}))
    assert names.index(INSTALL_STEP) < first_use


def test_every_set_a_job_names_is_in_megoocolab_toml(ci):
    sets = tomllib.loads((ROOT / "megoocolab.toml").read_text())["services"]
    named = {name for job in ci["jobs"].values() for line in runs(job) for name in re.findall(r"services run (\S+)", line)}
    assert named == {"test", "image", "web", "stack"}
    assert named <= set(sets)


def test_ci_never_runs_the_release_only_checks(ci):
    for job in ci["jobs"].values():
        for line in runs(job):
            assert "versions.py plan" not in line
            assert "versions.py guard" not in line
            assert "release-check" not in line
