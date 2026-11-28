from auth_helpers import add_grant, make_group, make_server, signed_in

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
AUDITOR = "aud@example.com"
NOBODY = "nobody@example.com"


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [server["name"] for server in response.json()]


async def two_groups():
    """staging holds web-01 and Db-02, production holds app-03."""
    staging = await make_group("staging")
    production = await make_group("production")
    await make_server(staging.id, "web-01", tags=("web", "eu-west"))
    await make_server(staging.id, "Db-02", tags=("db", "eu-west"))
    await make_server(production.id, "app-03", tags=("web", "us-east"))
    return staging, production


async def test_a_staging_only_admin_lists_only_staging_servers(api, clock):
    staging, _ = await two_groups()
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        response = await client.get("/api/servers")

    assert names(response) == ["Db-02", "web-01"]
    web = response.json()[1]
    assert (web["group_id"], web["group_name"], web["tags"]) == (str(staging.id), "staging", ["eu-west", "web"])


async def test_an_owner_and_an_auditor_list_every_server_by_name(api, clock):
    await two_groups()
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
    ):
        for client in (owner, auditor):
            assert names(await client.get("/api/servers")) == ["app-03", "Db-02", "web-01"]


async def test_a_person_without_roles_lists_none(api, clock):
    await two_groups()
    async with signed_in(api, clock, NOBODY) as (_, client):
        response = await client.get("/api/servers")

    assert (response.status_code, response.json()) == (200, [])


async def test_can_manage_follows_the_role(api, clock):
    staging, production = await two_groups()
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        await add_grant(ada.id, production.id, "operator")
        response = await client.get("/api/servers")

    assert names(response) == ["app-03", "Db-02", "web-01"]
    assert {server["name"]: server["can_manage"] for server in response.json()} == {
        "app-03": False,
        "Db-02": True,
        "web-01": True,
    }


async def test_can_view_logs_follows_view_logs_and_the_os(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    web = await make_server(staging.id, "web-01")
    await make_server(staging.id, "win-02", os="windows", port=3389)
    await make_server(production.id, "app-03")
    async with (
        signed_in(api, clock, ADMIN) as (ada, client),
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
    ):
        await add_grant(ada.id, staging.id, "operator", view_logs=True)
        await add_grant(ada.id, production.id, "operator", view_logs=False)
        response = await client.get("/api/servers")
        one = await client.get(f"/api/servers/{web.id}")
        seen = {
            label: {server["name"]: server["can_view_logs"] for server in (await other.get("/api/servers")).json()}
            for label, other in (("owner", owner), ("auditor", auditor))
        }

    assert {server["name"]: server["can_view_logs"] for server in response.json()} == {
        "app-03": False,
        "web-01": True,
        "win-02": False,
    }
    assert (one.status_code, one.json()["can_view_logs"]) == (200, True)
    assert seen == {
        "owner": {"app-03": True, "web-01": True, "win-02": False},
        "auditor": {"app-03": False, "web-01": False, "win-02": False},
    }


async def test_filters_by_group(api, clock):
    staging, production = await two_groups()
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        assert names(await owner.get("/api/servers", params={"group_id": str(production.id)})) == ["app-03"]
        assert names(await owner.get("/api/servers", params={"group_id": str(staging.id)})) == ["Db-02", "web-01"]


async def test_filters_by_one_tag(api, clock):
    await two_groups()
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        assert names(await owner.get("/api/servers", params={"tag": "web"})) == ["app-03", "web-01"]


async def test_filters_by_two_tags_needs_both(api, clock):
    await two_groups()
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        assert names(await owner.get("/api/servers", params={"tag": ["web", "eu-west"]})) == ["web-01"]
        assert names(await owner.get("/api/servers", params={"tag": ["db", "us-east"]})) == []


async def test_a_tag_filter_ignores_case(api, clock):
    await two_groups()
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        assert names(await owner.get("/api/servers", params={"tag": " DB "})) == ["Db-02"]


async def test_a_group_the_person_does_not_see_gives_an_empty_list(api, clock):
    staging, production = await two_groups()
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        response = await client.get("/api/servers", params={"group_id": str(production.id)})

    assert (response.status_code, response.json()) == (200, [])


async def test_server_tags_holds_only_the_tags_of_servers_the_person_sees(api, clock):
    staging, _ = await two_groups()
    async with (
        signed_in(api, clock, ADMIN) as (ada, admin),
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, NOBODY) as (_, nobody),
    ):
        await add_grant(ada.id, staging.id, "admin")
        for client, tags in (
            (admin, ["db", "eu-west", "web"]),
            (owner, ["db", "eu-west", "us-east", "web"]),
            (nobody, []),
        ):
            response = await client.get("/api/server-tags")
            assert (response.status_code, response.json()) == (200, tags)
