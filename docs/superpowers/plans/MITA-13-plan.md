# MITA-13 plan: Release workflow, pulled images and the first release `v0.1.0`

**Goal:** a push to `main` that carries a new version tests it, publishes `ghcr.io/mmhy2003/megooitadmin-backend` and `-frontend` (`:X.Y.Z` and `:latest`, amd64 and arm64) and creates the GitHub release `vX.Y.Z`; a server pulls these images and upgrades with `make upgrade`.

**Architecture:** `docker-compose.yml` names the GHCR images and builds nothing. A new overlay, `docker-compose.build.yml`, builds both images from the checkout under local names for `make up STACK=dev|e2e` and the `stack` service set. `.github/workflows/release.yml` runs `plan` → (`tests` ∥ `app`) → `images` (four native builds pushed by digest) → `publish` (tags, then `gh release create`). Its text is tested in `backend/tests/test_workflows.py`, as `ci.yml` is.

All test commands run from `backend/`. Never run `make up` or `make upgrade` without `STACK=` on this machine (AGENTS.md, "Safety").

## File map

| File | Step | Responsibility |
|---|---|---|
| `docker-compose.yml` | 1 | `frontend`/`backend`: `image: ghcr.io/mmhy2003/megooitadmin-<name>:${MEGOOITADMIN_VERSION:-latest}`, no `build:` |
| `docker-compose.build.yml` (new) | 1 | Builds both from the checkout as `megooitadmin-<name>:${MEGOOITADMIN_VERSION:-dev}` |
| `megoocolab.toml` | 1 | `stack` set: the overlay in `compose`, `MEGOOITADMIN_VERSION = "${MEGOO_SERVICES_PROJECT}"` |
| `tools/stacks/dev.env`, `tools/stacks/e2e.env` | 1 | `MEGOOITADMIN_VERSION=dev` / `=e2e` |
| `Makefile` | 1, 2 | Stacks add the overlay (1); real `up` loses `--build`, new `upgrade`, help (2) |
| `backend/tests/test_makefile.py` | 1, 2 | Stack file list (1); `up`, `upgrade` (2) |
| `backend/tests/test_stack.py` | 1, 3 | Compose as written, overlay, local image names (1); the two audit events (3) |
| `.env.example` | 2 | `#MEGOOITADMIN_VERSION=latest` with one sentence on pinning |
| `.github/workflows/release.yml` (new) | 4 | The Release workflow |
| `backend/tests/test_workflows.py` | 4 | Tests of `release.yml` |
| `README.md`, `AGENTS.md`, `docs/releasing.md` | 5 | Install pulls, Upgrade, dev copy builds; never `make upgrade`; workflow, failed runs, one-time actions |

Not changed: `tools/release/versions.py`, `ci.yml`, the Dockerfiles, the `test`/`migrate`/`image`/`web` sets, the Caddyfile. `docker-compose.build.yml` is not in `versions.py`'s `PRODUCT`, so it needs no version bump.

---

## Step 1. Compose names the GHCR images; the stacks and the stack set build through `docker-compose.build.yml`

### Tests first

`backend/tests/test_makefile.py`: change the constant

```python
STACK_FILES = "-f docker-compose.yml -f docker-compose.build.yml -f tools/fake-server/docker-compose.stack.yml"
```

(every stack test uses it). Run `megoocolab-runner services run test -- uv run pytest tests/test_makefile.py`: the stack tests fail (the Makefile still lists two files).

`backend/tests/test_stack.py`:

- Add `import yaml` and `BUILD_FILE = ROOT / "docker-compose.build.yml"`, `GHCR = "ghcr.io/mmhy2003/megooitadmin-"`.
- `_compose` and `_compose_with_fake_server` pass `-f COMPOSE_FILE -f BUILD_FILE` (and then `-f FAKE_SERVER_FILE`), because the set now starts the stack with the overlay.
- Update the module docstring: the set built the stack from this checkout through `docker-compose.build.yml`.
- New tests, placed after `test_docker_compose_yml_holds_no_fake_server`:

```python
def _written(path: Path) -> dict:
    return yaml.safe_load(path.read_text())["services"]


def test_docker_compose_yml_pulls_the_two_release_images_and_builds_nothing():
    services = _written(COMPOSE_FILE)
    for name in ("backend", "frontend"):
        assert services[name]["image"] == f"{GHCR}{name}:${{MEGOOITADMIN_VERSION:-latest}}"
    assert {name for name, service in services.items() if "build" in service} == set()


def test_the_build_overlay_builds_exactly_the_two_images_under_local_names():
    services = _written(BUILD_FILE)
    assert set(services) == {"backend", "frontend"}
    for name, service in services.items():
        assert service["build"] == f"./{name}"
        assert service["image"] == f"megooitadmin-{name}:${{MEGOOITADMIN_VERSION:-dev}}"
        assert "/" not in service["image"].split(":")[0]  # no registry


def test_the_stack_runs_the_images_it_built_under_its_own_tag():
    project = _env("MEGOO_SERVICES_PROJECT")
    for name in ("backend", "frontend"):
        container = _compose("ps", "-q", name).stdout.strip()
        inspected = subprocess.run(["docker", "inspect", "--format", "{{.Config.Image}}", container], capture_output=True, text=True, timeout=30)
        assert inspected.stdout.strip() == f"megooitadmin-{name}:{project}"
```

Run `megoocolab-runner services run stack -- uv run pytest -m stack`: the three new tests fail (`build` in `docker-compose.yml`, no overlay file, images unnamed).

### Implementation

`docker-compose.yml`: in `frontend` replace `build: ./frontend` with `image: ghcr.io/mmhy2003/megooitadmin-frontend:${MEGOOITADMIN_VERSION:-latest}`; in `backend` replace `build: ./backend` with `image: ghcr.io/mmhy2003/megooitadmin-backend:${MEGOOITADMIN_VERSION:-latest}`. Add to the header comment: "A server pulls the release images; docker-compose.build.yml builds them from the checkout for the dev and e2e stacks."

`docker-compose.build.yml` (new):

```yaml
# Builds the images from this checkout, for make up STACK=dev|e2e and the stack check. Local names: a build
# never replaces a pulled release image.
services:
  frontend:
    image: megooitadmin-frontend:${MEGOOITADMIN_VERSION:-dev}
    build: ./frontend
  backend:
    image: megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}
    build: ./backend
```

`megoocolab.toml`, `[services.stack]`:

```toml
description = "The whole Compose stack built from this checkout (docker-compose.build.yml: caddy, frontend, backend, db) and the fake sshd server, for pytest -m stack"
compose = ["docker-compose.yml", "docker-compose.build.yml", "tools/fake-server/docker-compose.stack.yml"]
```

and in `[services.stack.env]`:

```toml
# Each check builds and starts its own images, under its own project name.
MEGOOITADMIN_VERSION = "${MEGOO_SERVICES_PROJECT}"
```

`tools/stacks/dev.env`: add `MEGOOITADMIN_VERSION=dev`. `tools/stacks/e2e.env`: add `MEGOOITADMIN_VERSION=e2e`.

`Makefile`, the STACK branch:

```make
# The dev and e2e stacks build the images from this checkout (docker-compose.build.yml) and also run the fake
# server (tools/fake-server), on the servers network.
COMPOSE := docker compose -p megooitadmin-$(STACK) --env-file tools/stacks/$(STACK).env -f docker-compose.yml -f docker-compose.build.yml -f tools/fake-server/docker-compose.stack.yml
```

### Verify

`megoocolab-runner services run test -- uv run pytest` and `megoocolab-runner services run stack -- uv run pytest -m stack`: all pass. Commit `feat(compose): a server pulls the release images and the dev stacks build them from the checkout`.

---

## Step 2. `make up` starts the published images, `make upgrade` pulls and restarts

### Tests first (`backend/tests/test_makefile.py`)

- Constants: `UP = "up -d --wait --wait-timeout 300"` (the real instance) and `UP_BUILD = "up -d --build --wait --wait-timeout 300"` (the stacks). Replace `UP` by `UP_BUILD` in `test_up_with_a_stack_uses_its_own_project_and_env_file_and_never_env` and `test_up_with_a_stack_authorizes_its_key_in_the_fake_server`.
- `TARGETS` gains `"upgrade"`.
- `test_up_creates_env_then_starts_the_real_instance_and_waits` also asserts `"--build" not in result.stdout`.
- `test_the_real_instance_never_gets_a_fake_server`: parametrize `["up", "upgrade", "down"]`.
- New:

```python
def test_upgrade_completes_env_then_pulls_then_restarts_the_real_instance(workdir):
    result = make(workdir, "-n", "upgrade")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "docker compose pull" in lines
    assert f"docker compose {UP}" in lines
    out = result.stdout
    assert out.index("/dev/urandom") < out.index("docker compose pull") < out.index(f"docker compose {UP}")
    assert not (workdir / ".env").exists()


@pytest.mark.parametrize("stack", ["dev", "e2e"])
def test_upgrade_with_a_stack_stops_and_runs_nothing(workdir, stack):
    bin_dir = workdir / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/bin/sh\ntouch "$(dirname "$0")/ran"\n')
    docker.chmod(0o755)
    result = make(workdir, "upgrade", f"STACK={stack}", path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode != 0
    assert "make upgrade acts on the real instance only" in result.stderr
    assert not (bin_dir / "ran").exists()
    assert not (workdir / ".env").exists()
```

Run `megoocolab-runner services run test -- uv run pytest tests/test_makefile.py`: the new and changed tests fail.

### Implementation (`Makefile`)

- `.PHONY` gains `upgrade`.
- In the `ifeq ($(STACK),)` branch add `UP := up -d --wait --wait-timeout 300` with the comment `# The real instance runs the published images: up pulls only what is missing, upgrade pulls the newest.`; in the STACK branch add `UP := up -d --build --wait --wait-timeout 300`.
- `up:` recipe: `$(COMPOSE) $(UP)` (the key step for stacks unchanged).
- New target after `up`:

```make
# Pulls every image of the stack (MEGOOITADMIN_VERSION in .env, latest by default) and restarts what changed.
# Run git pull first, so the Compose file belongs to the same release.
upgrade: $(ENV_FILE)
ifneq ($(STACK),)
	@echo "make upgrade acts on the real instance only: the dev and e2e stacks build from the checkout, use make up STACK=$(STACK)" >&2; exit 1
endif
	$(COMPOSE) pull
	$(COMPOSE) $(UP)
```

- `help`: `up` → `Start the stack and wait until it is healthy (creates or completes .env first). The real instance pulls missing images; STACK=dev|e2e builds from this checkout`; new line `upgrade                Pull the newest images of the release in .env and restart (git pull first; real instance only)`; the last line names `up, upgrade, down, …`.

`.env.example`, after `MEGOOITADMIN_HTTP_PORT`:

```
# The release the stack runs: latest follows every release (make upgrade pulls it). Set a version, for example
# 0.1.0, to stay on that release until you change this line.
#MEGOOITADMIN_VERSION=latest
```

### Verify

`megoocolab-runner services run test -- uv run pytest tests/test_makefile.py`, then the whole `megoocolab-runner services run test -- uv run pytest`. Commit `feat(make): make up starts the published images and make upgrade pulls the newest`.

---

## Step 3. The stack check proves the Phase 0 exit criterion: both audit events

`backend/tests/test_stack.py`: `from uuid import UUID`, a helper and two assertions at the end of `test_the_owner_pins_and_tests_the_fake_server_and_a_swapped_key_is_refused`:

```python
def _audit_of_server(server_id: str) -> list[tuple[str, str]]:
    """(action, result) of each audit event of the server, oldest first, read as the database owner."""
    UUID(server_id)  # only a UUID goes into the SQL
    sql = f"SELECT action, result FROM audit_log WHERE target_type = 'server' AND target_id = '{server_id}' ORDER BY seq"
    result = _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin", "-d", "megooitadmin", "-tA", "-F", "|", "-c", sql,
    )
    assert result.returncode == 0, result.stderr
    return [tuple(line.split("|")) for line in result.stdout.splitlines() if line]
```

```python
    events = _audit_of_server(server_id)
    assert ("server.created", "success") in events
    assert ("server.connection_tested", "success") in events
```

The events are already recorded (`app/inventory/servers.py:181`, `app/inventory/connection.py:282`), so this passes at once. Prove it can fail: temporarily expect `server.connection_testedX`, run `megoocolab-runner services run stack -- uv run pytest -m stack`, see the failure, revert, run again: pass. Commit `test(stack): registering and testing the fake server leaves both audit events`.

---

## Step 4. The Release workflow `release.yml`, tested by its text

Action versions are those of MegooColab's running Release workflow (MC-Q1) and of this repository's `ci.yml`: `actions/checkout@v7`, `actions/setup-python@v7`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/build-push-action@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`; arm64 runner `ubuntu-24.04-arm`. Before committing, open each action's GitHub releases page and confirm that major is still the newest; if one is newer, use it (the tests check only the action name).

A job that calls a reusable workflow (`tests`) may not set `timeout-minutes`; `ci.yml` gives each of its jobs one, and `test_workflows.py` already checks that.

### Tests first (append to `backend/tests/test_workflows.py`)

```python
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
    assert last.lstrip().startswith("# a second run")  or 'gh release view "v$VERSION"' in last
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
```

(Drop the redundant first `assert last...` line in `test_publish…` if it reads oddly; the `for part` loop is the check.)

Run `megoocolab-runner services run test -- uv run pytest tests/test_workflows.py`: every new test fails (`release.yml` does not exist).

### Implementation: `.github/workflows/release.yml`

```yaml
# A push to main releases MegooITAdmin when VERSION has no tag yet: every check, a start of the stack from the new
# images, the images on GHCR as :X.Y.Z and :latest, then the release vX.Y.Z with its note from docs/releases/.
# A push with no new version runs plan only. Nothing is public before publish. docs/releasing.md has the routine.
name: Release

on:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: release
  cancel-in-progress: false

env:
  REGISTRY: ghcr.io/mmhy2003

jobs:
  plan:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    outputs:
      release: ${{ steps.plan.outputs.release }}
      version: ${{ steps.plan.outputs.version }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0 # the tags: plan compares VERSION with the last one
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version-file: backend/.python-version
      # fails when the version files disagree, the product changed without a higher version, or the note is not in git
      - id: plan
        run: python tools/release/versions.py plan >> "$GITHUB_OUTPUT"

  tests:
    needs: plan
    if: needs.plan.outputs.release == 'true'
    uses: ./.github/workflows/ci.yml

  # What an admin does on a new server, from images built here under the names a server pulls. It runs beside tests
  # and publishes nothing: images, which pushes, waits for both.
  app:
    needs: plan
    if: needs.plan.outputs.release == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      VERSION: ${{ needs.plan.outputs.version }}
      MEGOOITADMIN_VERSION: smoke
      MEGOOITADMIN_HTTP_PORT: 127.0.0.1:8080
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: docker/setup-buildx-action@v4
      - name: Build the backend for this machine
        uses: docker/build-push-action@v7
        with:
          context: backend
          platforms: linux/amd64
          load: true
          tags: ${{ env.REGISTRY }}/megooitadmin-backend:smoke
          build-args: APP_VERSION=${{ env.VERSION }}
      - name: Build the frontend for this machine
        uses: docker/build-push-action@v7
        with:
          context: frontend
          platforms: linux/amd64
          load: true
          tags: ${{ env.REGISTRY }}/megooitadmin-frontend:smoke
      # make up without STACK= acts on the real instance (AGENTS.md, "Safety"). This GitHub machine is new and has none.
      - name: Start the stack as an admin does
        run: |
          make up
          curl -fsS http://127.0.0.1:8080/api/health
          test "$(docker compose exec -T backend printenv APP_VERSION)" = "$VERSION"
      - name: Stack logs (on failure)
        if: failure()
        run: docker compose logs --no-color
      - name: Remove the stack
        if: always()
        run: docker compose down --volumes

  # One job per image and platform, each on a machine of its own architecture: under QEMU, MegooColab's arm64
  # frontend build crashed. Each build is pushed by digest, without a tag; publish tags them together.
  images:
    needs: [plan, tests, app]
    if: needs.plan.outputs.release == 'true'
    permissions:
      contents: read
      packages: write
    strategy:
      fail-fast: true
      matrix:
        image: [backend, frontend]
        platform:
          - { arch: amd64, runner: ubuntu-24.04 }
          - { arch: arm64, runner: ubuntu-24.04-arm }
    runs-on: ${{ matrix.platform.runner }}
    timeout-minutes: 45
    env:
      VERSION: ${{ needs.plan.outputs.version }}
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push by digest
        id: build
        uses: docker/build-push-action@v7
        with:
          context: ${{ matrix.image }}
          platforms: linux/${{ matrix.platform.arch }}
          # the frontend declares no APP_VERSION: Docker warns and ignores it
          build-args: APP_VERSION=${{ env.VERSION }}
          labels: org.opencontainers.image.source=https://github.com/${{ github.repository }}
          outputs: type=image,name=${{ env.REGISTRY }}/megooitadmin-${{ matrix.image }},push-by-digest=true,name-canonical=true,push=true
      - name: Keep the digest
        env:
          DIGEST: ${{ steps.build.outputs.digest }}
          IMAGE: ${{ matrix.image }}
          ARCH: ${{ matrix.platform.arch }}
        run: |
          mkdir -p digests
          printf '%s\n' "$DIGEST" > "digests/$IMAGE-$ARCH"
      - uses: actions/upload-artifact@v7
        with:
          name: digest-${{ matrix.image }}-${{ matrix.platform.arch }}
          path: digests/
          retention-days: 1

  publish:
    needs: [plan, images]
    if: needs.plan.outputs.release == 'true'
    permissions:
      contents: write
      packages: write
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    env:
      VERSION: ${{ needs.plan.outputs.version }}
      IMAGES: backend frontend # the images matrix; a test keeps both lists and docker-compose.yml equal
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/download-artifact@v8
        with:
          pattern: digest-*
          merge-multiple: true
          path: digests
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Tag both platforms as one image
        run: |
          for image in $IMAGES; do
            name="$REGISTRY/megooitadmin-$image"
            docker buildx imagetools create -t "$name:$VERSION" -t "$name:latest" \
              "$name@$(cat "digests/$image-amd64")" "$name@$(cat "digests/$image-arm64")"
            docker buildx imagetools inspect "$name:$VERSION"
          done
      - name: Create the release, which creates the tag
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GH_REPO: ${{ github.repository }}
        run: |
          # a second run of a failed job finds the release already made
          gh release view "v$VERSION" > /dev/null 2>&1 || gh release create "v$VERSION" --target "$GITHUB_SHA" \
            --title "MegooITAdmin $VERSION" --notes-file "docs/releases/v$VERSION.md" --latest
```

Also update the first comment of `.github/workflows/ci.yml`? No: it already says release.yml reuses it.

### Verify

`megoocolab-runner services run test -- uv run pytest tests/test_workflows.py`, then the whole test set. If `actionlint` is available (`docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest`, from the repository root), run it on both workflows and fix what it reports. Commit `ci: the Release workflow tests, starts, publishes and releases a new version`.

---

## Step 5. Documentation: install pulls, upgrade, never `make upgrade` here, the workflow in `docs/releasing.md`

`README.md`, "Run it":
- `make up` "creates `.env`, pulls the images of the latest release (`ghcr.io/mmhy2003/megooitadmin-backend` and `-frontend`, amd64 and arm64) and starts Caddy, the frontend, the backend and the database". It pulls only images that are missing.
- New `### Upgrade` after "First start": `git pull`, then `make upgrade`. `git pull` first, so the Compose file and the images belong to the same release. `make upgrade` pulls every image of the stack (Caddy and the database included) and restarts what changed. Set `MEGOOITADMIN_VERSION=0.1.0` in `.env` to stay on a release; `make upgrade` then pulls that version until the line changes. Each release note's "Upgrading" says what else a release needs.
- "A second copy": `make up STACK=dev` builds the images from this checkout (`docker-compose.build.yml`) under the local names `megooitadmin-backend:dev` and `-frontend:dev`; `make upgrade` refuses a `STACK=`.

`AGENTS.md`, "Safety", new bullet after the `STACK=` bullet: "Never run `make upgrade`: it pulls new images and restarts the owner's real instance. It refuses `STACK=`; a dev or e2e stack takes `make up STACK=…` again." Also in "Checks": the stack set builds through `docker-compose.build.yml`.

`docs/releasing.md`:
- Version numbers: `docker-compose.build.yml` joins the list of files that need no version (it only builds the dev and e2e stacks and the stack check).
- Replace "What the workflow does" with the five jobs as built in step 4: `plan` (outputs `release`, `version`; no new version → only `plan` runs, green); `tests` (`ci.yml`) beside `app` (builds both images here as `:smoke`, `make up` with `MEGOOITADMIN_VERSION=smoke` on `127.0.0.1:8080`, `curl /api/health`, checks the backend's `APP_VERSION`, always removes the stack); `images` (four native builds, amd64 on `ubuntu-24.04`, arm64 on `ubuntu-24.04-arm`, pushed by digest without a tag); `publish` (`:X.Y.Z` and `:latest`, then `gh release create vX.Y.Z --latest`, which creates the tag). Rights: `contents: read` by default, `images` adds `packages: write`, `publish` has `contents: write` and `packages: write`. No layer cache, no QEMU. The workflow never runs `git tag` or `git push` and never edits or deletes a release.
- New "When a run fails": `tests`, `app` or `images` → nothing is public (at most untagged builds); run the failed jobs again for a passing fault, otherwise fix through a work branch into `develop`, merge `develop` into `main` again and push, same version. `publish` after the image tags and before the release → run it again (both steps repeat safely); with a new commit instead, the image tag `X.Y.Z` moves to the new build (an image tag of a release never announced, not the git tag). Once the release exists `plan` says `release=false`; a mistake is fixed with a patch release. arm64 failure (no wheel) or an arm64 runner that never starts: report it, never drop arm64.
- New "Once, after the first release": make the two GHCR packages public (GitHub creates them private), or `docker login ghcr.io` on every server, else `make up` ends with "denied". The owner's own instance: `make up` now pulls `latest`, so before `v0.1.0` exists it fails; a running stack keeps running.

### Verify

Every check of AGENTS.md "Checks": `megoocolab-runner services run test -- uv run pytest`, `megoocolab-runner services run image -- uv run pytest -m docker`, in `frontend/` `npx tsc --noEmit`, `npm test`, `megoocolab-runner services run web -- npm run test:image`, `megoocolab-runner services run stack -- uv run pytest -m stack`, `make test-security`, `uv run --project backend pytest tools/release`, `python tools/release/versions.py check`. By hand: `make up STACK=dev`, `curl http://127.0.0.1:8080/api/health` → `{"status":"ok"}`, `make down STACK=dev`. Never `make up`/`make upgrade` without `STACK=`. Commit `docs: install pulls the release images, make upgrade, and the Release workflow`.

---

## Final verification

From `backend/`:

```bash
megoocolab-runner services run test -- uv run pytest
megoocolab-runner services run image -- uv run pytest -m docker
megoocolab-runner services run stack -- uv run pytest -m stack
make -C .. test-security
```

From the root: `uv run --project backend pytest tools/release`, `python tools/release/versions.py check`; from `frontend/`: `npx tsc --noEmit`, `npm test`, `megoocolab-runner services run web -- npm run test:image`. Then `make up STACK=dev`, `curl http://127.0.0.1:8080/api/health`, `make down STACK=dev`. The pull request into `develop` must have a green CI run.

## After the merge (not a step of this pull request)

When the owner says "release": the nine steps of AGENTS.md. Step 1 lists `git log develop`, step 4 changes nothing, step 5 writes `docs/releases/v0.1.0.md` from the text in the design (compared with `git log develop` first, adding anything merged after the design), step 7 pushes `main` and starts the workflow. Done when `gh release list --limit 1` shows `v0.1.0` as Latest, every job of the Release run is green, and `docker buildx imagetools inspect ghcr.io/mmhy2003/megooitadmin-backend:0.1.0` (and `-frontend:0.1.0`) lists `linux/amd64` and `linux/arm64`. Then the owner makes the GHCR packages public.
