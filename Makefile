# MegooITAdmin's entry point. Run `make` for the list of targets. Recipes need a POSIX shell: on Windows,
# run make from Git Bash.
#
# Without STACK, the stack targets act on the real instance: project megooitadmin, port 80, .env.
# STACK=dev or STACK=e2e acts on megooitadmin-dev (port 8080) or megooitadmin-e2e (port 8081) instead,
# with the throwaway values of tools/stacks/<STACK>.env. Those never read .env.

.DEFAULT_GOAL := help
.PHONY: help .env up down logs migrate shell-backend migration test test-security release-check setup-code reset-mfa reset-password

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
	@echo "  setup-code             Print a new one-time setup code (only before the first account exists)"
	@echo "  reset-mfa email=<email>       Make <email> set up a new authenticator at the next sign-in"
	@echo "  reset-password email=<email>  Set a new password for <email> and unlock the account"
	@echo "  migration name=<name>  Create the next numbered migration on the scratch database"
	@echo "  test                   Run every backend, frontend and stack check"
	@echo "  test-security          Run the security suites"
	@echo "  release-check          Check the versions and the release plan"
	@echo ""
	@echo "Without STACK, up, down, logs, migrate, shell-backend, setup-code, reset-mfa and reset-password act on the real instance."

# Only the real instance reads .env. A missing file is created with both passwords and AUTH_SECRET_KEY. A file
# without POSTGRES_API_PASSWORD or AUTH_SECRET_KEY gets the missing line appended. No line is ever changed or removed.
.env:
	@if [ ! -e .env ]; then \
		pw=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
		key=$$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n'); \
		if ! printf '%s%s%s' "$$pw" "$$api" "$$key" | grep -Eqx '[0-9a-f]{128}'; then \
			echo "Could not read a random password from /dev/urandom: .env was not written." >&2; exit 1; \
		fi; \
		(umask 077; printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_API_PASSWORD=%s\nAUTH_SECRET_KEY=%s\n' "$$pw" "$$api" "$$key" > .env); \
		echo "Created .env with new database passwords and the key that encrypts the authenticator secrets. Keep this file: the database keeps the owner's password it was first started with."; \
	else \
		if ! grep -q '^POSTGRES_API_PASSWORD=' .env; then \
			api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
			if ! printf '%s' "$$api" | grep -Eqx '[0-9a-f]{32}'; then \
				echo "Could not read a random password from /dev/urandom: .env was not changed." >&2; exit 1; \
			fi; \
			if [ -s .env ] && [ -n "$$(tail -c 1 .env)" ]; then echo >> .env; fi; \
			printf 'POSTGRES_API_PASSWORD=%s\n' "$$api" >> .env; \
			echo "Added POSTGRES_API_PASSWORD to .env: the backend now serves as the restricted role megooitadmin_api."; \
		fi; \
		if ! grep -q '^AUTH_SECRET_KEY=' .env; then \
			key=$$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n'); \
			if ! printf '%s' "$$key" | grep -Eqx '[0-9a-f]{64}'; then \
				echo "Could not read a random key from /dev/urandom: .env was not changed." >&2; exit 1; \
			fi; \
			if [ -s .env ] && [ -n "$$(tail -c 1 .env)" ]; then echo >> .env; fi; \
			printf 'AUTH_SECRET_KEY=%s\n' "$$key" >> .env; \
			echo "Added AUTH_SECRET_KEY to .env: it encrypts the authenticator secrets. Keep this file."; \
		fi; \
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

setup-code:
	$(COMPOSE) exec backend python -m app.auth.cli setup-code

# The email is checked by the shell from the environment, before make puts it into a command.
reset-mfa:
	@case "$$email" in ''|*[!A-Za-z0-9.@_+-]*|*@*@*) echo "make reset-mfa needs an email, for example: make reset-mfa email=owner@example.com" >&2; exit 1;; esac
	$(COMPOSE) exec backend python -m app.auth.cli reset-mfa "$(email)"

reset-password:
	@case "$$email" in ''|*[!A-Za-z0-9.@_+-]*|*@*@*) echo "make reset-password needs an email, for example: make reset-password email=owner@example.com" >&2; exit 1;; esac
	$(COMPOSE) exec backend python -m app.auth.cli reset-password "$(email)"

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
