# MegooITAdmin's entry point. Run `make` for the list of targets. Recipes need a POSIX shell: on Windows,
# run make from Git Bash.
#
# Without STACK, the stack targets act on the real instance: project megooitadmin, port 80, .env.
# STACK=dev or STACK=e2e acts on megooitadmin-dev (port 8080) or megooitadmin-e2e (port 8081) instead,
# with the throwaway values of tools/stacks/<STACK>.env. Those never read .env.

.DEFAULT_GOAL := help
.PHONY: help up down logs migrate shell-backend migration test test-security release-check

RUNNER := megoocolab-runner
VERSIONS := backend/migrations/versions

ifeq ($(STACK),)
COMPOSE := docker compose
ENV_FILE := .env
else ifeq ($(filter-out dev e2e,$(STACK))$(word 2,$(STACK)),)
COMPOSE := docker compose -p megooitadmin-$(STACK) --env-file tools/stacks/$(STACK).env
ENV_FILE :=
else
$(error STACK must be dev or e2e)
endif

help:
	@echo "Usage: make <target> [STACK=dev|STACK=e2e]"
	@echo ""
	@echo "  up                     Build and start the stack, and wait until it is healthy (creates .env first)"
	@echo "  down                   Stop the stack. The database volume stays"
	@echo "  logs                   Follow the logs of the stack"
	@echo "  migrate                Apply the migrations in the running backend"
	@echo "  shell-backend          Open a shell in the running backend"
	@echo "  migration name=<name>  Create the next numbered migration on the scratch database"
	@echo "  test                   Run every backend, frontend and stack check"
	@echo "  test-security          Run the security suites"
	@echo "  release-check          Check the versions and the release plan"
	@echo ""
	@echo "Without STACK, up, down, logs, migrate and shell-backend act on the real instance."

# Only the real instance reads .env, and an existing file is never touched.
.env:
	@pw=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
	if ! printf '%s' "$$pw" | grep -Eqx '[0-9a-f]{32}'; then \
		echo "Could not read a random password from /dev/urandom: .env was not written." >&2; exit 1; \
	fi; \
	(umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$$pw" > .env); \
	echo "Created .env with a new database password. Keep this file: the database keeps the password it was first started with."

up: $(ENV_FILE)
	$(COMPOSE) up -d --build --wait --wait-timeout 300

# Never with -v: the database volume holds the data.
down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) exec backend alembic upgrade head

shell-backend:
	$(COMPOSE) exec backend bash
