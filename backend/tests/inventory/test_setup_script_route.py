from auth_helpers import actions, signed_in

from app.ssh import setup


async def test_a_signed_in_person_downloads_the_bundled_script(api, clock):
    async with signed_in(api, clock, "otto@example.com") as (_, client):
        before = await actions()
        response = await client.get("/api/ssh/setup-script")
        after = await actions()

    assert response.status_code == 200, response.text
    assert response.text == setup.script_text()
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert response.headers["content-disposition"] == 'attachment; filename="megoo-setup.sh"'
    assert after == before


async def test_401_when_signed_out(api):
    response = await api.get("/api/ssh/setup-script")

    assert response.status_code == 401
