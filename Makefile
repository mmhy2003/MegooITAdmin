# MegooITAdmin's entry point. Run `make` for the list of targets. Recipes need a POSIX shell: on Windows,
# run make from Git Bash.
#
# Without STACK, the stack targets act on the real instance: project megooitadmin, port 80, .env.
# STACK=dev or STACK=e2e acts on megooitadmin-dev (port 8080) or megooitadmin-e2e (port 8081) instead,
# with the throwaway values of tools/stacks/<STACK>.env. Those never read .env.

.DEFAULT_GOAL := help
.PHONY: help .env up down logs migrate shell-backend migration test test-security release-check

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
	@echo "  up                     Build and start the stack, and wait until it is healthy (creates or completes .env first)"
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

# Only the real instance reads .env. A missing file is created with both passwords. A file without
# POSTGRES_API_PASSWORD gets one appended. No line is ever changed or removed.
.env:
	@if [ ! -e .env ]; then \
		pw=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
		if ! printf '%s%s' "$$pw" "$$api" | grep -Eqx '[0-9a-f]{64}'; then \
			echo "Could not read a random password from /dev/urandom: .env was not written." >&2; exit 1; \
		fi; \
		(umask 077; printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_API_PASSWORD=%s\n' "$$pw" "$$api" > .env); \
		echo "Created .env with new database passwords. Keep this file: the database keeps the owner's password it was first started with."; \
	elif ! grep -q '^POSTGRES_API_PASSWORD=' .env; then \
		api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
		if ! printf '%s' "$$api" | grep -Eqx '[0-9a-f]{32}'; then \
			echo "Could not read a random password from /dev/urandom: .env was not changed." >&2; exit 1; \
		fi; \
		if [ -s .env ] && [ -n "$$(tail -c 1 .env)" ]; then echo >> .env; fi; \
		printf 'POSTGRES_API_PASSWORD=%s\n' "$$api" >> .env; \
		echo "Added POSTGRES_API_PASSWORD to .env: the backend now serves as the restricted role megooitadmin_api."; \
	fi

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

# The highest migration number plus one, with four digits. The leading 1 keeps 0008 from being read as octal.
LAST_MIGRATION = $(lastword $(sort $(foreach file,$(notdir $(wildcard $(VERSIONS)/[0-9][0-9][0-9][0-9]_*.py)),$(firstword $(subst _, ,$(file))))))
NEXT_MIGRATION = $(shell printf '%04d' $$((1$(or $(LAST_MIGRATION),0000) - 10000 + 1)))
REQUIRE_RUNNER = @command -v $(RUNNER) >/dev/null 2>&1 || { echo "make $@ needs $(RUNNER) on PATH: it starts the throwaway databases of the checks." >&2; exit 1; }

# The name is checked by the shell from the environment, before make puts it into a command.
migration:
	@case "$$name" in ''|[!a-z]*|*[!a-z0-9_]*) echo "make migration needs a name of a-z, 0-9 and _ that starts with a letter, for example: make migration name=add_users" >&2; exit 1;; esac
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic revision --autogenerate --rev-id $(NEXT_MIGRATION) -m "$(subst _, ,$(name))"'

test:
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run test -- uv run pytest
	cd frontend && if [ ! -d node_modules ]; then npm ci; fi && npx tsc --noEmit && npm test
	cd backend && $(RUNNER) services run image -- uv run pytest -m docker
	cd frontend && $(RUNNER) services run web -- npm run test:image
	cd backend && $(RUNNER) services run stack -- uv run pytest -m stack

test-security:
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run test -- uv run pytest tests/security

release-check:
	python tools/release/versions.py check
	python tools/release/versions.py plan
