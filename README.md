# MegooITAdmin

## Run it

You need Docker with Compose v2 and GNU Make. On Windows, run `make` from Git Bash.

    make up

This builds and starts Caddy, the frontend, the backend and the database, and returns once the app answers.
The app is then at `http://<this host>/`, and `curl http://localhost/api/health` gives `{"status":"ok"}`.
`make down` stops it and keeps the data; `make` lists every target.

- **`.env`.** The first `make up` creates `.env` with two random database passwords. `POSTGRES_PASSWORD` is the
  owner's, used only at start-up to migrate. `POSTGRES_API_PASSWORD` belongs to `megooitadmin_api`, the
  restricted role the backend serves as. Keep this file: the database keeps the owner's password it was first
  started with, so a new one would lock the backend out. `make up` adds `POSTGRES_API_PASSWORD` to an older
  `.env` and changes nothing else. `.env.example` explains every variable.
- **The port.** Caddy is the only service with a published port, 80 by default. Set `MEGOOITADMIN_HTTP_PORT` in
  `.env` to use another one, or an address and port such as `127.0.0.1:8080` (for example when port 80 is taken
  or Docker is rootless).
- **TLS.** Caddy serves plain HTTP. Put a TLS proxy in front of it on a private address: Caddy trusts the
  `X-Forwarded-*` headers only from private addresses.
- **A second copy.** `make up STACK=dev` starts the project `megooitadmin-dev` on `127.0.0.1:8080`, beside the
  real one, with throwaway values. Pass the same `STACK=dev` to `down`, `logs`, `migrate` and `shell-backend`.
