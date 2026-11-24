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


RELEASE_NEEDS = {"plan": set(), "tests": {"plan"}, "app": {"plan"}, "images": {"plan", "tests", "app"}, "publish": {"plan", "images"}}
RELEASING = "needs.plan.outputs.release == 'true'"
FORBIDDEN = ["git tag", "git push", "gh release delete", "gh release edit", "--force", "--clobber"]
GHCR = "ghcr.io/mmhy2003/megooitadmin-"


@pytest.fixture
def release() -> dict:
    return workflow("release.yml")


def needs(job: dict) -> set[str]:
    value = job.get("needs", [])
    return {value} if isinstance(value, str) else set(value)


def all_steps(wf: dict) -> list[tuple[str, dict]]:
    return [(name, step) for name, job in wf["jobs"].items() for step in job.get("steps", [])]


def steps_using(job: dict, action: str) -> list[dict]:
    return [step for step in job["steps"] if step.get("uses", "").startswith(f"{action}@")]


def test_release_runs_only_on_pushes_to_main(release):
    assert release[True] == {"push": {"branches": ["main"]}}


def test_only_images_and_publish_get_more_than_read(release):
    assert release["permissions"] == {"contents": "read"}
    granted = {name: job["permissions"] for name, job in release["jobs"].items() if "permissions" in job}
    assert granted == {"images": {"contents": "read", "packages": "write"}, "publish": {"contents": "write", "packages": "write"}}


def test_releases_queue_and_are_never_cancelled(release):
    assert release["concurrency"] == {"group": "release", "cancel-in-progress": False}


def test_release_has_the_five_jobs_in_order(release):
    assert {name: needs(job) for name, job in release["jobs"].items()} == RELEASE_NEEDS


def test_every_job_but_plan_runs_only_for_a_new_version(release):
    for name, job in release["jobs"].items():
        if name == "plan":
            assert "if" not in job
        else:
            assert job["if"] == RELEASING, name


def test_plan_reads_the_tags_and_writes_its_outputs(release):
    plan = release["jobs"]["plan"]
    assert plan["steps"][0]["with"]["fetch-depth"] == 0
    step = next(step for step in plan["steps"] if step.get("id") == "plan")
    assert step["run"] == 'python tools/release/versions.py plan >> "$GITHUB_OUTPUT"'
    assert plan["outputs"] == {"release": "${{ steps.plan.outputs.release }}", "version": "${{ steps.plan.outputs.version }}"}


def test_tests_runs_the_whole_ci_workflow(release):
    assert release["jobs"]["tests"]["uses"] == "./.github/workflows/ci.yml"


def test_app_starts_the_smoke_images_with_make_up_and_always_removes_them(release):
    app = release["jobs"]["app"]
    assert app["env"]["MEGOOITADMIN_VERSION"] == "smoke"
    assert app["env"]["MEGOOITADMIN_HTTP_PORT"] == "127.0.0.1:8080"
    builds = steps_using(app, "docker/build-push-action")
    assert {(b["with"]["context"], b["with"]["tags"]) for b in builds} == {
        (name, "${{ env.REGISTRY }}/megooitadmin-" + name + ":smoke") for name in ("backend", "frontend")
    }
    assert all(b["with"]["load"] is True and "push" not in b["with"] for b in builds)
    script = "\n".join(runs(app))
    assert "make up" in script and "STACK=" not in script
    assert script.index("make up") < script.index("curl -fsS http://127.0.0.1:8080/api/health")
    assert 'printenv APP_VERSION)" = "$VERSION"' in script
    assert any(s.get("if") == "failure()" and "docker compose logs" in s.get("run", "") for s in app["steps"])
    assert (app["steps"][-1]["if"], app["steps"][-1]["run"]) == ("always()", "docker compose down --volumes")


def test_images_builds_each_platform_natively_and_pushes_by_digest(release):
    images = release["jobs"]["images"]
    platforms = images["strategy"]["matrix"]["platform"]
    assert {p["arch"]: p["runner"] for p in platforms} == {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}
    assert images["runs-on"] == "${{ matrix.platform.runner }}"
    (build,) = steps_using(images, "docker/build-push-action")
    w = build["with"]
    assert w["platforms"] == "linux/${{ matrix.platform.arch }}"
    assert w["build-args"] == "APP_VERSION=${{ env.VERSION }}"
    assert w["labels"].startswith("org.opencontainers.image.source=")
    assert "push-by-digest=true" in w["outputs"] and "push=true" in w["outputs"]
    assert "tags" not in w
    assert steps_using(images, "actions/upload-artifact")


def test_no_qemu_and_no_layer_cache(release):
    for name, step in all_steps(release):
        assert not step.get("uses", "").startswith("docker/setup-qemu-action@"), name
        assert not {"cache-from", "cache-to"} & set(step.get("with", {})), name


def test_publish_tags_both_platforms_then_creates_the_latest_release(release):
    publish = release["jobs"]["publish"]
    script = "\n".join(runs(publish))
    assert '-t "$name:$VERSION" -t "$name:latest"' in script
    last = publish["steps"][-1]["run"]
    for part in ['gh release view "v$VERSION" > /dev/null 2>&1 ||', 'gh release create "v$VERSION"', '--target "$GITHUB_SHA"',
                 '--title "MegooITAdmin $VERSION"', '--notes-file "docs/releases/v$VERSION.md"', "--latest"]:
        assert part in last
    assert script.index("imagetools create") < script.index("gh release create")


def test_no_step_moves_a_tag_or_changes_a_release(release):
    for name, step in all_steps(release):
        for word in FORBIDDEN:
            assert word not in step.get("run", ""), (name, word)


def test_no_script_pastes_an_expression(release):
    # The version reaches the scripts only as $VERSION: an expression in a script's text could inject code.
    for name, step in all_steps(release):
        assert "${{" not in step.get("run", ""), name


def test_the_workflow_publishes_exactly_the_images_compose_pulls(release):
    pulled = {name for name, s in yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"].items() if s.get("image", "").startswith(GHCR)}
    built = set(yaml.safe_load((ROOT / "docker-compose.build.yml").read_text())["services"])
    matrix = set(release["jobs"]["images"]["strategy"]["matrix"]["image"])
    published = set(release["jobs"]["publish"]["env"]["IMAGES"].split())
    assert pulled == built == matrix == published == {"backend", "frontend"}


def test_every_job_has_a_timeout_and_every_checkout_keeps_no_credentials(release):
    for name, job in release["jobs"].items():
        if "uses" in job:  # a called workflow takes no timeout: ci.yml gives each of its jobs one
            continue
        assert 0 < job["timeout-minutes"] <= 60, name
    checkouts = [(name, s) for name, s in all_steps(release) if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 4  # plan, app, images, publish
    for name, step in checkouts:
        assert step["with"]["persist-credentials"] is False, name
