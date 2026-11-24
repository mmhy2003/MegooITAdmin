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

### People and access

- The Owner invites a person on Settings → Users and gets a one-time link. The app sends no email: pass the link
  on by hand. It is valid 7 days. The person opens it, chooses a password and sets up an authenticator.
- Roles are given per server group (Settings → Server groups). A person is Admin or Operator on each group, or
  has no access to it, and each group's role carries seven switches. Only Connect SSH and Connect RDP are checked
  so far; the other five are kept for the features that use them.
- Auditor and Owner are platform-wide and cover every group. Everyone sees their own access on Profile and
  security.
- An account is disabled, never deleted: its sessions end and it can be enabled again. Every change to a person,
  a role or a switch is recorded in the audit log with before and after.
- `make reset-password` and `make reset-mfa` still work for every account.

### Servers

- The Owner, and an Admin in their own groups, register, edit, move and remove servers on the Servers page.
  Moving a server to another group needs Admin on both groups.
- A server lives in exactly one server group, and the group decides who sees it: everyone with a role in the
  group sees it, and so do the Owner and Auditors. Nobody else does.
- Tags are free labels typed on the server. They filter the list and never decide access.
- A group that still holds servers cannot be deleted: move or remove its servers first.
- Prepare the account `megoo` on each Linux server: not root, and not in the `docker` group. MegooITAdmin never
  signs in as root, and refuses root as the login account.
- The platform's public key, for `megoo`'s `authorized_keys`, is on each server's Platform access card, and
  `make ssh-public-key` prints it.
- The Owner, or an Admin of the server's group, pins the server's host key after comparing its fingerprint with
  the one on the server: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
- People with Connect SSH in the group test the connection from the server page.
- A changed host key blocks the server until an Admin accepts the new key, with a reason, or keeps the pinned one.
  Every step is in the audit log.
- Back up the `ssh_key` Docker volume: it holds the platform's private key, and a lost key means a new one has to
  go on every server.
- Windows servers connect from Phase 2.
