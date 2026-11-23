"""One walk through every auth flow: each auth action is audited, and no event holds a secret."""

import re
from datetime import timedelta

import pyotp
from auth_helpers import EMAIL, NAME, PASSWORD, actions, audit_rows, code_for
from httpx import AsyncClient, Response

from app.audit import verify_chain
from app.auth import cli, recovery, sessions
from app.auth.actions import ALL_ACTIONS
from app.core.db import SessionLocal

NEW_PASSWORD = "a brand new and long passphrase"
CLI_PASSWORD = "the passphrase the host typed in"
SETUP_CODE = re.compile("Setup code: (" + recovery.CODE_PATTERN + ")")


class Walk:
    """The clients of the walk, and every secret it typed or was shown."""

    def __init__(self, api: AsyncClient, clock, capsys) -> None:
        self.api = api
        self.clock = clock
        self.capsys = capsys
        self.secrets: set[str] = {PASSWORD, NEW_PASSWORD, CLI_PASSWORD}
        self.totp_secret = ""
        self.recovery_codes: list[str] = []

    async def call(self, client: AsyncClient, method: str, url: str, **kw) -> Response:
        response = await client.request(method, url, **kw)
        if token := client.cookies.get(sessions.COOKIE):
            self.secrets.add(token)
        return response

    def post(self, url: str, body: dict | None = None, client: AsyncClient | None = None):
        return self.call(client or self.api, "POST", url, json=body if body is not None else {})

    def totp_code(self, secret: str | None = None) -> str:
        """The current code of the secret, kept as a secret, then the clock moves on so the next code is new."""
        code = code_for(secret or self.totp_secret, self.clock.now)
        self.secrets.add(code)
        self.clock.advance(seconds=30)
        return code

    def wrong_code(self) -> str:
        """A 6-digit code that matches none of the steps the check accepts now."""
        accepted = {pyotp.TOTP(self.totp_secret).at(self.clock.now + timedelta(seconds=d)) for d in (-30, 0, 30)}
        code = next(c for c in (f"{n:06d}" for n in range(314159, 1_000_000)) if c not in accepted)
        self.secrets.add(code)
        return code

    def keep_recovery_codes(self, codes: list[str]) -> None:
        assert len(codes) == recovery.RECOVERY_CODE_COUNT
        self.recovery_codes = codes
        self.secrets.update(codes)
        self.secrets.update(recovery.normalise_code(code) for code in codes)

    def login(self, email: str = EMAIL, password: str = PASSWORD, client: AsyncClient | None = None):
        return self.post("/api/auth/login", {"email": email, "password": password}, client)

    async def enrol(self, body: dict | None = None) -> None:
        response = await self.post("/api/auth/mfa/enrol", body)
        assert response.status_code == 200, response.text
        self.totp_secret = response.json()["secret"]
        self.secrets.add(self.totp_secret)


async def setup(walk: Walk) -> None:
    assert await cli.create_setup_code(if_no_account=False) == 0
    code = SETUP_CODE.search(walk.capsys.readouterr().out).group(1)
    walk.secrets.update({code, recovery.normalise_code(code)})
    body = {"name": NAME, "email": EMAIL, "password": PASSWORD}
    assert (await walk.post("/api/auth/setup", {**body, "code": "AAAA-BBBB-CCCC-DDDD"})).status_code == 401
    assert (await walk.post("/api/auth/setup", {**body, "code": code})).status_code == 200


async def first_enrolment(walk: Walk) -> None:
    await walk.enrol()
    response = await walk.post("/api/auth/mfa/enrol/confirm", {"code": walk.totp_code()})
    assert response.status_code == 200, response.text
    walk.keep_recovery_codes(response.json()["recovery_codes"])


async def logout(walk: Walk) -> None:
    assert (await walk.post("/api/auth/logout")).status_code == 200


async def unknown_email(walk: Walk) -> None:
    assert (await walk.login(email="nobody@example.com")).status_code == 401


async def wrong_password(walk: Walk) -> None:
    assert (await walk.login(password="not the right passphrase")).status_code == 401


async def wrong_code_then_recovery_code(walk: Walk) -> None:
    assert (await walk.login()).status_code == 200
    wrong = await walk.post("/api/auth/login/mfa", {"code": walk.wrong_code(), "method": "totp"})
    assert wrong.status_code == 401
    typed = walk.recovery_codes[0].lower().replace("-", " ")
    walk.secrets.add(typed)
    response = await walk.post("/api/auth/login/mfa", {"code": typed, "method": "recovery_code"})
    assert response.status_code == 200, response.text


async def second_browser_revoked(walk: Walk) -> None:
    async with AsyncClient(transport=walk.api._transport, base_url="http://test") as other:
        assert (await walk.login(client=other)).status_code == 200
        response = await walk.post("/api/auth/login/mfa", {"code": walk.totp_code()}, other)
        assert response.status_code == 200, response.text
        listed = (await walk.call(walk.api, "GET", "/api/auth/sessions")).json()
        (theirs,) = [s["id"] for s in listed if not s["current"]]
        assert (await walk.call(walk.api, "DELETE", f"/api/auth/sessions/{theirs}")).status_code == 204
        assert (await walk.call(other, "GET", "/api/auth/me")).status_code == 401


async def change_password(walk: Walk) -> None:
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert (await walk.post("/api/auth/password", body)).status_code == 200


async def new_recovery_codes(walk: Walk) -> None:
    response = await walk.post("/api/auth/recovery-codes", {"code": walk.totp_code()})
    assert response.status_code == 200, response.text
    walk.keep_recovery_codes(response.json()["recovery_codes"])


async def replace_authenticator(walk: Walk) -> None:
    await walk.enrol({"code": walk.totp_code(), "method": "totp"})
    response = await walk.post("/api/auth/mfa/enrol/confirm", {"code": walk.totp_code()})
    assert response.status_code == 200, response.text


async def lock_with_five_wrong_passwords(walk: Walk) -> None:
    for _ in range(5):
        assert (await walk.login(password="not the right passphrase")).status_code == 401


async def host_resets(walk: Walk) -> None:
    assert await cli.reset_password(EMAIL, CLI_PASSWORD) == 0
    assert await cli.reset_mfa(EMAIL) == 0


async def test_one_walk_records_every_auth_action_and_no_secret(api, clock, capsys):
    walk = Walk(api, clock, capsys)

    await setup(walk)
    await first_enrolment(walk)
    await logout(walk)
    await unknown_email(walk)
    await wrong_password(walk)
    await wrong_code_then_recovery_code(walk)
    await second_browser_revoked(walk)
    await change_password(walk)
    await new_recovery_codes(walk)
    await replace_authenticator(walk)
    await lock_with_five_wrong_passwords(walk)
    await host_resets(walk)

    assert set(await actions()) == ALL_ACTIONS
    async with SessionLocal() as session:
        assert (await verify_chain(session)).ok
    leaks = [(secret, row) for row in await audit_rows() for secret in walk.secrets if secret in row]
    assert leaks == []
