"""One walk through every access and user flow: each action is audited, and no event holds a secret."""

from auth_helpers import PASSWORD, actions, audit_rows, code_for, make_user, other_client, sign_in
from httpx import AsyncClient, Response

from app.access.actions import ACCESS_DENIED
from app.access.permissions import Permission
from app.audit import verify_chain
from app.auth import actions as auth_actions
from app.auth import recovery, sessions
from app.core.db import SessionLocal
from app.inventory import actions as inventory_actions
from app.users import actions as user_actions

PASSWORD_ADA = "ada chose this long passphrase"
WRONG_TOKEN = "a-token-that-was-never-handed-out"


def grant(group_id: str, role: str = "admin", **switches: bool) -> dict:
    """A grant as the request names it: every switch off unless given."""
    return {"group_id": group_id, "role": role, **{p.value: False for p in Permission}, **switches}


class Walk:
    """The Owner's and Ada's clients, and every secret the walk typed or was shown."""

    def __init__(self, api: AsyncClient, ada: AsyncClient, clock) -> None:
        self.api = api
        self.ada = ada
        self.clock = clock
        self.secrets: set[str] = {PASSWORD, PASSWORD_ADA, WRONG_TOKEN}
        self.groups: dict[str, str] = {}
        self.ada_id = ""

    async def call(self, client: AsyncClient, method: str, url: str, body: dict | None = None) -> Response:
        response = await client.request(method, url, json=body)
        if token := client.cookies.get(sessions.COOKIE):
            self.secrets.add(token)
        return response

    async def owner(self, method: str, url: str, body: dict | None = None, status: int = 200) -> Response:
        response = await self.call(self.api, method, url, body)
        assert response.status_code == status, response.text
        return response

    def keep_link(self, link: dict) -> str:
        self.secrets.add(link["token"])
        return link["token"]


async def create_groups(walk: Walk) -> None:
    for name in ("staging", "production"):
        response = await walk.owner("POST", "/api/server-groups", {"name": name})
        walk.groups[name] = response.json()["id"]
    await walk.owner("PATCH", f"/api/server-groups/{walk.groups['production']}", {"description": "Live"})


async def invite_ada(walk: Walk) -> str:
    body = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "platform_role": None,
        "grants": [grant(walk.groups["staging"], connect_ssh=True, view_logs=True)],
    }
    link = (await walk.owner("POST", "/api/users", body)).json()
    walk.ada_id = link["user_id"]
    return walk.keep_link(link)


async def ada_accepts_and_enrols(walk: Walk, token: str) -> None:
    assert (await walk.call(walk.ada, "POST", "/api/auth/invite/check", {"token": token})).status_code == 200
    accept = "/api/auth/invite/accept"
    refused = await walk.call(walk.ada, "POST", accept, {"token": WRONG_TOKEN, "password": PASSWORD_ADA})
    assert refused.status_code == 404
    accepted = await walk.call(walk.ada, "POST", accept, {"token": token, "password": PASSWORD_ADA})
    assert accepted.status_code == 200, accepted.text

    started = await walk.call(walk.ada, "POST", "/api/auth/mfa/enrol", {})
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    code = code_for(secret, walk.clock.now)
    walk.secrets.update({secret, code})
    confirmed = await walk.call(walk.ada, "POST", "/api/auth/mfa/enrol/confirm", {"code": code})
    assert confirmed.status_code == 200, confirmed.text
    codes = confirmed.json()["recovery_codes"]
    walk.secrets.update(codes)
    walk.secrets.update(recovery.normalise_code(c) for c in codes)
    walk.clock.advance(seconds=30)


async def change_adas_access(walk: Walk) -> None:
    staging, production = walk.groups["staging"], walk.groups["production"]
    url = f"/api/users/{walk.ada_id}/access"
    steps = [
        # A switch, then the role in a group, then a group added and removed.
        {"platform_role": None, "grants": [grant(staging, connect_ssh=True)]},
        {"platform_role": None, "grants": [grant(staging, "operator", connect_ssh=True)]},
        {"platform_role": None, "grants": [grant(staging, "operator", connect_ssh=True), grant(production)]},
        {"platform_role": None, "grants": [grant(staging, "operator", connect_ssh=True)]},
        # The platform role, and back to the group role.
        {"platform_role": "auditor", "grants": []},
        {"platform_role": None, "grants": [grant(staging, "operator", connect_ssh=True)]},
    ]
    for body in steps:
        await walk.owner("PUT", url, body, status=204)


async def ada_is_denied_users(walk: Walk) -> None:
    assert (await walk.call(walk.ada, "GET", "/api/users")).status_code == 403


async def second_invite_renewed(walk: Walk) -> None:
    body = {"name": "Bo Brown", "email": "bo@example.com", "platform_role": "auditor", "grants": []}
    link = (await walk.owner("POST", "/api/users", body)).json()
    walk.keep_link(link)
    walk.keep_link((await walk.owner("POST", f"/api/users/{link['user_id']}/invite")).json())


async def owner_manages_ada(walk: Walk) -> None:
    for action in ("disable", "enable", "mfa-reset"):
        await walk.owner("POST", f"/api/users/{walk.ada_id}/{action}", status=204)


async def delete_staging(walk: Walk) -> None:
    await walk.owner("DELETE", f"/api/server-groups/{walk.groups['staging']}", status=204)


async def test_one_walk_records_every_access_and_user_action_and_no_secret(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    async with other_client(api) as ada:
        walk = Walk(api, ada, clock)
        walk.secrets.add(secret)
        walk.secrets.add(api.cookies.get(sessions.COOKIE))

        await create_groups(walk)
        token = await invite_ada(walk)
        await ada_accepts_and_enrols(walk, token)
        await change_adas_access(walk)
        await ada_is_denied_users(walk)
        await second_invite_renewed(walk)
        await owner_manages_ada(walk)
        await delete_staging(walk)

    expected = (
        user_actions.ALL_ACTIONS
        | inventory_actions.ALL_ACTIONS
        | {ACCESS_DENIED, auth_actions.MFA_RESET, auth_actions.SESSION_REVOKED}
    )
    assert expected - set(await actions()) == set()
    async with SessionLocal() as session:
        assert (await verify_chain(session)).ok
    leaks = [(secret, row) for row in await audit_rows() for secret in walk.secrets if secret in row]
    assert leaks == []
