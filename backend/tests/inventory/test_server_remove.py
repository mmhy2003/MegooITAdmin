from uuid import uuid4

from auth_helpers import add_grant, events, make_group, make_server, signed_in
from conftest import owner_session
from sqlalchemy import func, select

from app.inventory.models import Server, ServerTag

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
OPERATOR = "otto@example.com"


async def rows_of(server_id) -> tuple[int, int]:
    """The servers and server_tags rows left for the server, read as the owner of the tables."""
    async with owner_session() as session:
        servers = await session.scalar(select(func.count()).select_from(Server).where(Server.id == server_id))
        tags = await session.scalar(select(func.count()).select_from(ServerTag).where(ServerTag.server_id == server_id))
        return servers, tags


async def test_an_admin_removes_a_server_and_its_tags(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01", port=2222, role="db", tags=("web", "eu-west"))
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        response = await client.delete(f"/api/servers/{server.id}")

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await rows_of(server.id) == (0, 0)

    (deleted,) = await events("server.deleted")
    assert (deleted.actor_id, deleted.result, deleted.mfa) == (str(ada.id), "success", True)
    assert (deleted.target_type, deleted.target_id, deleted.target_name) == ("server", str(server.id), "db-01")
    assert deleted.context == {"server_group_id": str(staging.id)}
    assert deleted.change == {
        "address": {"before": "10.0.0.1", "after": None},
        "connection_settings": {"before": {"username": "megoo"}, "after": None},
        "group": {"before": "staging", "after": None},
        "name": {"before": "db-01", "after": None},
        "os": {"before": "linux", "after": None},
        "port": {"before": 2222, "after": None},
        "role": {"before": "db", "after": None},
        "tags": {"before": ["eu-west", "web"], "after": None},
    }


async def test_a_server_without_role_or_tags_records_no_role(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.delete(f"/api/servers/{server.id}")

    assert response.status_code == 204, response.text
    (deleted,) = await events("server.deleted")
    assert "role" not in deleted.change
    assert deleted.change["tags"] == {"before": [], "after": None}


async def test_an_operator_cannot_remove_and_a_stranger_does_not_see_it(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    server = await make_server(staging.id, "db-01", tags=("web",))
    async with (
        signed_in(api, clock, OPERATOR) as (otto, operator),
        signed_in(api, clock, ADMIN) as (ada, stranger),
    ):
        await add_grant(otto.id, staging.id, "operator")
        await add_grant(ada.id, production.id, "admin")
        refused = await operator.delete(f"/api/servers/{server.id}")
        hidden = await stranger.delete(f"/api/servers/{server.id}")

    assert (refused.status_code, refused.json()) == (403, {"detail": "forbidden"})
    assert (hidden.status_code, hidden.json()) == (404, {"detail": "not_found"})
    assert await rows_of(server.id) == (1, 1)
    assert await events("server.deleted") == []


async def test_removing_a_server_that_does_not_exist_answers_404(api, clock):
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.delete(f"/api/servers/{uuid4()}")

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await events("server.deleted") == []
