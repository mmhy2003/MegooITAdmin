from auth_helpers import add_grant, make_group, make_user, sign_in

PERSON = "pat@example.com"


async def me_of(client) -> dict:
    response = await client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


async def test_me_lists_the_persons_group_roles_with_their_switches(api, clock):
    staging = await make_group("staging")
    production = await make_group("Production")
    await make_group("dev")
    pat, secret = await make_user(email=PERSON, name="Pat Person", platform_role=None)
    await add_grant(pat.id, staging.id, "admin", manage_playbooks=False)
    await add_grant(pat.id, production.id, "operator", connect_rdp=False)
    await sign_in(api, clock, secret, email=PERSON)

    body = await me_of(api)

    assert body["user"]["platform_role"] is None
    # By group name, whatever its case; a group without a role of Pat's is left out.
    assert body["grants"] == [
        {
            "group_id": str(production.id),
            "group_name": "Production",
            "role": "operator",
            "connect_ssh": True,
            "connect_rdp": False,
            "view_logs": True,
            "view_processes": True,
            "manage_processes": False,
            "run_playbooks": True,
            "manage_playbooks": False,
        },
        {
            "group_id": str(staging.id),
            "group_name": "staging",
            "role": "admin",
            "connect_ssh": True,
            "connect_rdp": True,
            "view_logs": True,
            "view_processes": True,
            "manage_processes": True,
            "run_playbooks": True,
            "manage_playbooks": False,
        },
    ]


async def test_me_of_an_owner_has_no_grants_and_platform_role_owner(api, clock):
    await make_group("staging")
    _, secret = await make_user()
    await sign_in(api, clock, secret)

    body = await me_of(api)

    assert (body["user"]["platform_role"], body["grants"]) == ("owner", [])


async def test_me_of_an_auditor(api, clock):
    await make_group("staging")
    _, secret = await make_user(email=PERSON, name="Aud Itor", platform_role="auditor")
    await sign_in(api, clock, secret, email=PERSON)

    body = await me_of(api)

    assert (body["user"]["platform_role"], body["grants"]) == ("auditor", [])
