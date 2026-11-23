# MegooITAdmin

## Run it

You need Docker with Compose v2 and GNU Make. On Windows, run `make` from Git Bash.

    make up

This builds and starts Caddy, the frontend, the backend and the database, and returns once the app answers.
The app is then at `http://<this host>/`, and `curl http://localhost/api/health` gives `{"status":"ok"}`.
`make down` stops it and keeps the data; `make` lists every target.

### First start

- After the first `make up` nobody can use the app yet. Run `make setup-code`, or look in `make logs` for
  `Setup code:`, then open the app: it shows the setup page.
- Enter the code, the Owner's name, email and a password of 12 to 128 characters. Then scan the QR code with an
  authenticator app and enter its code.
- Save the ten recovery codes: each signs in once if the phone is lost.
- Every sign-in then asks for the password and a code. A session ends after 1 hour without use and 12 hours after
  sign-in (`SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_MINUTES`).

- **`.env`.** The first `make up` creates `.env` with two random database passwords. `POSTGRES_PASSWORD` is the
  owner's, used only at start-up to migrate. `POSTGRES_API_PASSWORD` belongs to `megooitadmin_api`, the
  restricted role the backend serves as. Keep this file: the database keeps the owner's password it was first
  started with, so a new one would lock the backend out. `make up` adds `POSTGRES_API_PASSWORD` to an older
  `.env` and changes nothing else. `.env.example` explains every variable.
  `make up` also writes `AUTH_SECRET_KEY`, which encrypts the authenticator secrets. Keep it: with another key no
  code can be checked and everyone needs `make reset-mfa`. `make up` adds it to an older `.env`.
- **The port.** Caddy is the only service with a published port, 80 by default. Set `MEGOOITADMIN_HTTP_PORT` in
  `.env` to use another one, or an address and port such as `127.0.0.1:8080` (for example when port 80 is taken
  or Docker is rootless).
- **TLS.** Caddy serves plain HTTP. Put a TLS proxy in front of it on a private address: Caddy trusts the
  `X-Forwarded-*` headers only from private addresses.
- **A second copy.** `make up STACK=dev` starts the project `megooitadmin-dev` on `127.0.0.1:8080`, beside the
  real one, with throwaway values. Pass the same `STACK=dev` to `down`, `logs`, `migrate` and `shell-backend`.
- **API docs.** `/api/docs` is served only with `API_DOCS=true` in `.env`, and the dev stack sets it.

### Lost access

- `make reset-mfa email=<email>` makes that account set up a new authenticator at the next sign-in.
- `make reset-password email=<email>` asks twice for a new password, sets it and unlocks the account.
- Both end the account's sessions and are recorded in the audit log, and both take `STACK=` for the copies.
- After five failed attempts an account is locked for 15 minutes.
