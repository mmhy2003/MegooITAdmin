# MITA-13 design: Release workflow (`release.yml`), pulled images and the first release `v0.1.0`

## Goal

A push to `main` that carries a new version makes GitHub Actions test it, publish the backend and frontend images to GHCR (`:X.Y.Z` and `:latest`, amd64 and arm64) and create the GitHub release `vX.Y.Z` from its note. A server then pulls these images instead of building them, and an admin upgrades with `make upgrade`. After this task's pull request is merged, you say "release" and `v0.1.0` is cut with the routine that is already documented.

## What the repository looks like today

- `.github/workflows/ci.yml` runs seven checks and can be called by another workflow (`workflow_call`). There is no `release.yml`.
- `tools/release/versions.py plan` prints `release=true|false` and `version=X.Y.Z`. Today it fails only because `docs/releases/v0.1.0.md` is missing. There are no tags.
- `docker-compose.yml` builds `backend` and `frontend` from the checkout, and `make up` runs `up -d --build`. No image has a name (MITA-4 left the GHCR names to this task).
- `backend/Dockerfile` takes the build argument `APP_VERSION` (default `dev`). Nothing passes it yet.
- The runner (`megoocolab-runner services run`) always starts a set with `up -d --build --wait` and afterwards removes each image a set built, by its name. So an image that a set builds must never carry a GHCR name.
- The Audit page is still a placeholder: events are recorded, but no page shows them yet.

## Decisions

Your answers:

1. **Servers pull the published images.** `docker-compose.yml` names the GHCR images and has no `build:`. A new overlay builds from the checkout for the dev and e2e stacks and for the stack check. Rejected: keeping the build from the checkout, and doing the switch in a follow-up task. This differs from PRD §3.6 and §3.7, which still describe a build; the PRD text is not changed here.
2. **A server follows `latest`, and an upgrade is `make upgrade`.** `MEGOOITADMIN_VERSION` in `.env` pins a release. `make up` starts what is there and pulls only missing images. `make upgrade` pulls and restarts. The admin runs `git pull` first, so the Compose file and the images belong to the same release. Rejected: `make up` runs the version of the `VERSION` file, and `make up` always pulls.
3. **The release note is written at the release, from the text in this design** (below). This task's pull request does not contain it. The routine stays as documented: the release commit on `main` carries the note. Rejected: the note in this pull request.

Decisions I made (say so if you want one changed):

4. **Two images:** `ghcr.io/mmhy2003/megooitadmin-backend` and `ghcr.io/mmhy2003/megooitadmin-frontend`. These are the only services with a Dockerfile. A worker, the gateway or the executor joins the workflow in the task that adds it. A test stops a new GHCR service in the Compose file from being forgotten in the workflow.
5. **The overlay is `docker-compose.build.yml` at the root,** and it builds under local names: `megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}` and `megooitadmin-frontend:${MEGOOITADMIN_VERSION:-dev}`. A local build can then never replace a pulled release image, and the runner never removes one. The dev stack uses the tag `dev`, the e2e stack `e2e`, and the stack check its own project name (`${MEGOO_SERVICES_PROJECT}`), so two checks at once never start each other's build. This keeps MITA-4's rule that every project builds its own image. The overlay is not part of the product: a change to it needs no new version.
6. **`make upgrade` pulls every image of the stack** (`docker compose pull`), so it also brings the newest `caddy:2` and `timescale/timescaledb-ha:pg18`, as a new installation gets them. Rejected: pulling only MegooITAdmin's two images (a list in the Makefile to keep in step). `make upgrade STACK=…` stops with a message: those stacks build from the checkout.
7. **The smoke test (`app`) does what an admin does on a new server:** it builds both images on that machine under the GHCR names with the tag `smoke`, runs `make up` with `MEGOOITADMIN_VERSION=smoke`, then `curl /api/health` through Caddy. So it also proves that the Makefile writes a working `.env` and that the Compose file starts from named images with no build. It then checks that the backend reports the release's version. Rejected: a plain `docker compose up` with a hand-written env file, as MegooColab does (it would skip the Makefile).
8. **Nothing public happens before the last job.** `images` pushes each build by digest, without a tag. `publish` first gives every image its two tags, then creates the release, which creates the git tag. The workflow never runs `git tag` or `git push`, and never edits or deletes a release.
9. **Each job gets only the rights it needs.** The workflow's default is `contents: read`. `images` adds `packages: write`. `publish` has `contents: write` and `packages: write`. MegooColab gives both to every job; here the tests and the smoke test cannot publish.
10. **No Docker layer cache, and no QEMU.** Releases are rare, and MITA-12 made the same choice for CI. Each platform builds on a machine of its own architecture, because MegooColab's arm64 frontend build crashed under emulation.
11. **The workflow's text is tested** in `backend/tests/test_workflows.py`, as `ci.yml` is. A workflow runs only on GitHub, and this one runs for the first time at the release itself.
12. **The stack check also proves the Phase 0 exit criterion.** The test that registers the fake server and tests the connection also asserts that both actions are in the audit log (`server.created` and `server.connection_tested`). The release's `tests` job runs it on the release commit.

## Architecture

| File | Change |
|---|---|
| `.github/workflows/release.yml` | New: the workflow below |
| `docker-compose.yml` | `backend` and `frontend`: `image:` with the GHCR name, no `build:` |
| `docker-compose.build.yml` | New: the overlay that builds both from the checkout |
| `Makefile` | The stacks add the overlay; the real instance's `up` loses `--build`; new target `upgrade` |
| `megoocolab.toml` | The `stack` set adds the overlay and `MEGOOITADMIN_VERSION` |
| `tools/stacks/dev.env`, `e2e.env` | `MEGOOITADMIN_VERSION=dev` and `=e2e` |
| `.env.example` | `#MEGOOITADMIN_VERSION=latest`, with one sentence on pinning a release |
| `backend/tests/test_workflows.py` | New tests of `release.yml` |
| `backend/tests/test_makefile.py` | `up`, the stacks' files, `upgrade` |
| `backend/tests/test_stack.py` | The image names, the overlay, the two audit events |
| `README.md` | Install pulls; a short "Upgrade" part; the dev copy builds |
| `AGENTS.md` | Safety: never run `make upgrade` (it acts on the real instance) |
| `docs/releasing.md` | The workflow section, a failed run, and what you do once after the first release |

`tools/release/versions.py`, `ci.yml`, the Dockerfiles, the `test`, `migrate`, `image` and `web` sets and the Caddyfile do not change.

### Compose

`docker-compose.yml`:

```yaml
  frontend:
    image: ghcr.io/mmhy2003/megooitadmin-frontend:${MEGOOITADMIN_VERSION:-latest}
  backend:
    image: ghcr.io/mmhy2003/megooitadmin-backend:${MEGOOITADMIN_VERSION:-latest}
```

`docker-compose.build.yml`:

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

A local build passes no `APP_VERSION`, so it stays `dev`, as the Dockerfile says.

### Makefile

| Call | Compose command |
|---|---|
| `make up` | `docker compose up -d --wait --wait-timeout 300` (creates or completes `.env` first, as today) |
| `make upgrade` | completes `.env`, then `docker compose pull`, then `docker compose up -d --wait --wait-timeout 300` |
| `make up STACK=dev` | `docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env -f docker-compose.yml -f docker-compose.build.yml -f tools/fake-server/docker-compose.stack.yml up -d --build --wait --wait-timeout 300`, then the key step as today |
| `make upgrade STACK=dev` | Stops: "make upgrade acts on the real instance only: the dev and e2e stacks build from the checkout, use make up STACK=…" |

`make help` lists `upgrade`. Every other target is unchanged.

### `megoocolab.toml`, the `stack` set

```toml
compose = ["docker-compose.yml", "docker-compose.build.yml", "tools/fake-server/docker-compose.stack.yml"]
MEGOOITADMIN_VERSION = "${MEGOO_SERVICES_PROJECT}"   # in [services.stack.env]
```

### `release.yml`

```yaml
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
```

| Job | Needs | Runs on | Does |
|---|---|---|---|
| `plan` | | `ubuntu-24.04` | Checkout with `fetch-depth: 0` (the tags), Python from `backend/.python-version`, then `python tools/release/versions.py plan >> "$GITHUB_OUTPUT"`. Outputs `release` and `version` |
| `tests` | `plan` | (CI's own) | `uses: ./.github/workflows/ci.yml`: the seven checks |
| `app` | `plan` | `ubuntu-24.04` | The smoke test of decision 7. Prints the stack's logs when it fails, and always ends with `docker compose down --volumes` |
| `images` | `plan`, `tests`, `app` | `ubuntu-24.04` for amd64, `ubuntu-24.04-arm` for arm64 | One job per image and platform (four). Builds with `APP_VERSION` and the label `org.opencontainers.image.source`, pushes by digest, and keeps the digest as an artifact |
| `publish` | `plan`, `images` | `ubuntu-24.04` | For each image, `docker buildx imagetools create` joins both digests as `:X.Y.Z` and `:latest`. Then the release (below) |

- Every job except `plan` has `if: needs.plan.outputs.release == 'true'`. A push that needs no release runs `plan` only and stays green.
- `tests` and `app` run side by side. `images` waits for both, so nothing is pushed before every check passed.
- The version reaches the scripts only as the environment variable `VERSION`, never pasted into a script's text.
- Every job has a `timeout-minutes`, and every checkout has `persist-credentials: false`.
- The release step:

  ```bash
  # a second run of a failed job finds the release already made
  gh release view "v$VERSION" > /dev/null 2>&1 || gh release create "v$VERSION" --target "$GITHUB_SHA" \
    --title "MegooITAdmin $VERSION" --notes-file "docs/releases/v$VERSION.md" --latest
  ```

Notes for the plan:

- Confirm the current major versions of the actions (`actions/checkout`, `actions/setup-python`, `docker/setup-buildx-action`, `docker/login-action`, `docker/build-push-action`, `actions/upload-artifact`, `actions/download-artifact`) and the arm64 runner label in their documentation, not from memory. MegooColab's workflow (MC-Q1) is the model for the digest steps.
- `APP_VERSION` goes to both builds. The frontend's Dockerfile does not declare it, so Docker prints a warning there and ignores it. If the warning bothers, pass it to the backend only.

## Data and interfaces

- **Published:** `ghcr.io/mmhy2003/megooitadmin-backend` and `-frontend`, tags `X.Y.Z` (no `v`) and `latest`, each for `linux/amd64` and `linux/arm64`. Git tag and GitHub release `vX.Y.Z`, titled `MegooITAdmin X.Y.Z`, marked Latest.
- **New variable `MEGOOITADMIN_VERSION`:** the image tag a stack runs. Default `latest`. `0.1.0` in `.env` pins that release.
- **New target `make upgrade`.**
- **`plan` → later jobs:** `needs.plan.outputs.release` and `needs.plan.outputs.version`.
- No API, database or page changes.

### The release note `docs/releases/v0.1.0.md`

Written in step 5 of the routine. Before it is committed, it is compared with `git log develop`, and anything merged after this design is added.

```markdown
MegooITAdmin 0.1.0 is the first release, the base that the later features build on. An admin signs in with a password and an authenticator code, registers Linux servers, and checks that the platform reaches each one over SSH. Monitoring, logs, remote sessions and the AI agents come in later releases; their pages are in the sidebar as placeholders.

## New

- **One command installs it.** `make up` creates `.env`, pulls the images and starts Caddy, the frontend, the backend and the database. Only Caddy publishes a port (80, plain HTTP), so put your TLS proxy in front of it. The images are built for amd64 and arm64.
- **Nobody gets in without a password and an authenticator code.** The first person claims the installation with a one-time setup code from the host (`make setup-code`), sets up an authenticator app and gets ten recovery codes. A session ends after 1 hour without use and 12 hours after sign-in, and five failed attempts lock an account for 15 minutes.
- **The Owner invites people with a one-time link.** The app sends no email: pass the link on by hand within 7 days. An account is disabled, never deleted.
- **Roles are given per server group.** A person is Admin or Operator on each group, or has no access to it. Owner and Auditor cover every group. Each group's role carries seven switches; only Connect SSH and Connect RDP are checked so far.
- **Servers live in groups, and the group decides who sees them.** The Owner, and an Admin in their own groups, register, edit, move and remove servers. Tags filter the list and never decide access.
- **The platform connects only to a server whose host key you pinned.** Compare the fingerprint with the one on the server, pin it, then test the connection from the server page. A changed host key blocks the server until an Admin accepts the new key, with a reason, or keeps the pinned one. The platform signs in as the account `megoo` and refuses root.
- **Every action is recorded in an audit log that cannot be changed quietly.** Each event carries the hash of the one before it, and the backend's database account may add events but not change or delete them. The page that shows the log comes in a later release.

## Upgrading

This is the first release, so there is nothing to upgrade from. To install it, clone the repository, run `make up`, then `make setup-code`, and open the app. Keep `.env`, and back up the `db_data` and `ssh_key` Docker volumes: the first holds your data, the second the platform's SSH key. From the next release on, an upgrade is `git pull`, then `make upgrade`.
```

### Cutting `v0.1.0`

This happens after this task's pull request is merged into `develop` and CI is green there, when you say "release". The agent follows the nine steps of `AGENTS.md`. For this first release: step 1 lists `git log develop`, step 4 changes nothing, step 5 writes the note above, and step 7 pushes `main`, which starts the workflow for the first time.

Once, by you, after the first release:

1. **Make the two GHCR packages public** (GitHub creates them private), or run `docker login ghcr.io` on every server. Until then `make up` on a server ends with "denied".
2. **Your own real instance** today runs images built on your machine. After this task, `make up` there pulls `latest` instead. Before `v0.1.0` exists there is nothing to pull, so `make up` fails until the release is out; a stack that is already running keeps running.

## Error handling and edge cases

- **A push to `main` with no new version** (the merge back, a documentation fix): `plan` prints `release=false` and the other jobs are skipped.
- **`plan` fails** (the version files disagree, the product changed without a higher version, the note is not in git): nothing is built. The message names the file.
- **`tests`, `app` or `images` fails:** nothing is public. No tag, no release and no image tag exists, only untagged builds in GHCR at most. For a passing fault, run the failed jobs again. For a real defect, fix it through a work branch into `develop`, merge `develop` into `main` again and push. The version stays the same, because no tag exists yet, so `plan` passes.
- **`publish` fails after the image tags and before the release:** run the job again. Joining the digests can be repeated, and the release step skips a release that exists. If a new commit is needed instead, the image tag `X.Y.Z` moves to the new build. That is an image tag of a release that was never announced, not the git tag.
- **After the release exists,** `plan` says `release=false` for that version, so no later run can publish it again. The git tag is never moved or deleted. A mistake is fixed with a patch release.
- **Two pushes to `main` close together** wait for each other (`concurrency: release`, never cancelled).
- **arm64:** the backend image has no compiler. If a dependency has no arm64 wheel, the arm64 build fails and the release stops. Report it; do not drop arm64.
- **The arm64 runner is not available to the repository** (a private repository on a plan without it): the job waits and then ends at its timeout. Report it to the owner.
- **`make upgrade` without `git pull`:** new images may run with an older Compose file. The README and every note's "Upgrading" say `git pull` first.
- **`make up` on a server that cannot reach GHCR:** it works when the images are already on the machine, because `up` pulls only what is missing. `make upgrade` fails with Docker's message and changes nothing that runs.
- **A pinned version** (`MEGOOITADMIN_VERSION=0.1.0`): `make upgrade` pulls that same version, so the server stays on it until the line is changed.
- **Port 80 in the smoke test:** the job sets `MEGOOITADMIN_HTTP_PORT=127.0.0.1:8080`.
- **`make up` in `release.yml` has no `STACK=`.** The rule in `AGENTS.md` protects your machine; a GitHub machine is new and has no real instance. A comment in the workflow says so.

## Testing

Tests are written first and seen failing.

**`megoocolab-runner services run test -- uv run pytest`**

`backend/tests/test_workflows.py`, for `release.yml`:

- it runs only on pushes to `main`;
- the default permission is `contents: read`, only `images` and `publish` have more, and each has exactly what decision 9 says;
- the concurrency group is `release` and is never cancelled;
- the jobs are exactly `plan`, `tests`, `app`, `images` and `publish`, with the `needs` of the table, and every job except `plan` runs only when `release` is `true`;
- `plan` fetches the whole history and writes `versions.py plan` to `$GITHUB_OUTPUT`;
- `tests` calls `./.github/workflows/ci.yml`;
- `app` builds both images with the tag `smoke`, runs `make up` with `MEGOOITADMIN_VERSION=smoke`, calls `/api/health`, and always removes the stack;
- `images` builds amd64 on `ubuntu-24.04` and arm64 on `ubuntu-24.04-arm`, pushes by digest with no tag, passes `APP_VERSION`, and uses no QEMU;
- `publish` tags `$VERSION` and `latest`, and its last step is the guarded `gh release create` with `--target "$GITHUB_SHA"`, the note file and `--latest`;
- no step contains `git tag`, `git push`, `gh release delete`, `gh release edit`, `--force` or `--clobber`;
- the images in `images`, the images in `publish`, the services with a GHCR image in `docker-compose.yml` and the services in `docker-compose.build.yml` are the same list;
- every job has a timeout, and every checkout has `persist-credentials: false`.

`backend/tests/test_makefile.py`:

- `make -n up` prints `docker compose up -d --wait --wait-timeout 300`, with no `--build`;
- `make -n up STACK=dev|e2e` prints the three files in order, with `--build`;
- `make -n upgrade` prints the `.env` step, then `docker compose pull`, then the `up` line;
- `make upgrade STACK=dev` stops with its message and runs nothing;
- plain `make` lists `upgrade`.

**`megoocolab-runner services run stack -- uv run pytest -m stack`** (`backend/tests/test_stack.py`):

- in `docker-compose.yml` as written, `backend` and `frontend` have the two GHCR image names with `${MEGOOITADMIN_VERSION:-latest}`, and no service has `build`;
- `docker-compose.build.yml` gives exactly these two services a `build` and a local image name without a registry;
- after the owner registers the fake server and tests the connection, the audit log holds `server.created` and `server.connection_tested` for that server;
- the existing stack tests still pass, now through the overlay.

**By hand in the build:** `make up STACK=dev`, `curl http://127.0.0.1:8080/api/health`, `make down STACK=dev`. The implementer never runs `make up` or `make upgrade` without `STACK=`. Every check of `AGENTS.md` runs before the pull request, and the pull request's own CI run must be green.

**What cannot be tested before the release:** `release.yml` itself, and the start of `docker-compose.yml` without the overlay. Both run for the first time when `main` is pushed. The `app` job exists for the second, and a failure there publishes nothing.

**The task is done when,** after the release: `gh release list --limit 1` shows `v0.1.0` as Latest, every job of the Release run is green (so the stack test proved the registration, the connection and both audit events on the release commit), and `docker buildx imagetools inspect ghcr.io/mmhy2003/megooitadmin-backend:0.1.0` and `-frontend:0.1.0` each list `linux/amd64` and `linux/arm64`.

## Out of scope

- Cutting the release inside this task's pull request. It follows the merge, when you say "release".
- Changing the PRD text (§3.6 and §3.7 still describe a build from the checkout).
- Pinning `caddy:2` and `timescale/timescaledb-ha:pg18` to exact versions.
- Images for the workers, the gateway and the executor: each joins with its own task.
- A Docker layer cache, a manual (`workflow_dispatch`) trigger, release-candidate tags, files attached to the release, image signing, and an update notice in the app.
- An Audit page, and any other change to pages or to the API.
- Branch protection, and the visibility of the GHCR packages: both are GitHub settings you change by hand.
