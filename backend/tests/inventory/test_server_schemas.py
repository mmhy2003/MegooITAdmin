from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.inventory.server_schemas import ServerIn, ServerPatch

GROUP = uuid4()


def server(**fields) -> ServerIn:
    """A valid server, with `fields` changed."""
    body = {"name": "db-01", "address": "10.0.0.1", "group_id": GROUP, "os": "linux", "port": 22}
    return ServerIn(**(body | fields))


def test_a_valid_server_keeps_its_values_and_has_defaults():
    body = server(role="database")

    assert body.name == "db-01"
    assert body.address == "10.0.0.1"
    assert body.group_id == GROUP
    assert body.os == "linux"
    assert body.port == 22
    assert body.role == "database"
    assert body.tags == []
    assert body.connection_settings.username == "megoo"


@pytest.mark.parametrize("name", ["db-01", "DB_01.eu", "a" * 64])
def test_a_good_name_passes(name):
    assert server(name=name).name == name


@pytest.mark.parametrize("name", ["", "-db", "db 01", "a" * 65])
def test_a_bad_name_fails(name):
    with pytest.raises(ValidationError):
        server(name=name)


@pytest.mark.parametrize(
    ("address", "kept"),
    [
        ("10.0.0.1", "10.0.0.1"),
        ("::1", "::1"),
        ("2001:DB8::1", "2001:db8::1"),
        ("Db-01.Example.com", "db-01.example.com"),
    ],
)
def test_a_good_address_is_kept_in_its_canonical_text(address, kept):
    assert server(address=address).address == kept


def long_host(length: int) -> str:
    """A host name of `length` characters made of valid labels."""
    labels = []
    while sum(len(label) + 1 for label in labels) < length:
        labels.append("a" * 63)
    return ".".join(labels)[:length].rstrip(".")


def test_a_host_name_of_253_characters_passes():
    host = long_host(253)
    assert len(host) == 253
    assert server(address=host).address == host


@pytest.mark.parametrize("address", ["bad host", "a..b", "-x.com", "", "x" * 64 + ".com"])
def test_a_bad_address_fails(address):
    with pytest.raises(ValidationError):
        server(address=address)


def test_a_host_name_of_254_characters_fails():
    host = long_host(253) + "a"
    assert len(host) == 254
    with pytest.raises(ValidationError):
        server(address=host)


@pytest.mark.parametrize("port", [1, 65535])
def test_a_port_in_range_passes(port):
    assert server(port=port).port == port


@pytest.mark.parametrize("port", [0, 65536])
def test_a_port_out_of_range_fails(port):
    with pytest.raises(ValidationError):
        server(port=port)


def test_windows_passes_and_bsd_fails():
    assert server(os="windows").os == "windows"
    with pytest.raises(ValidationError):
        server(os="bsd")


def test_tags_are_trimmed_lowercased_deduplicated_and_sorted():
    assert server(tags=[" Web", "web", "EU-west"]).tags == ["eu-west", "web"]


def test_twenty_tags_pass():
    tags = [f"t{i}" for i in range(20)]
    assert server(tags=tags).tags == sorted(tags)


@pytest.mark.parametrize(
    "tags",
    [["-x"], ["a b"], ["a" * 33], [f"t{i}" for i in range(21)]],
    ids=["leading-dash", "space", "33-chars", "21-tags"],
)
def test_bad_tags_fail(tags):
    with pytest.raises(ValidationError):
        server(tags=tags)


def test_an_empty_role_is_none():
    assert server(role="").role is None


def test_a_role_of_65_characters_fails():
    with pytest.raises(ValidationError):
        server(role="r" * 65)


def test_a_username_is_kept():
    assert server(connection_settings={"username": "deploy"}).connection_settings.username == "deploy"


@pytest.mark.parametrize("username", ["a b", ""])
def test_a_bad_username_fails(username):
    with pytest.raises(ValidationError):
        server(connection_settings={"username": username})


def test_an_unknown_connection_setting_fails():
    with pytest.raises(ValidationError):
        server(connection_settings={"username": "megoo", "password": "x"})


def test_a_patch_may_not_send_null_for_a_field_other_than_role():
    for field in ("name", "address", "group_id", "os", "port", "tags", "connection_settings"):
        with pytest.raises(ValidationError):
            ServerPatch(**{field: None})


def test_a_patch_may_clear_the_role():
    assert ServerPatch(role=None).role is None
    assert ServerPatch(role="").role is None


def test_a_patch_knows_which_fields_were_sent():
    patch = ServerPatch(port=2222, role=None)

    assert patch.model_fields_set == {"port", "role"}
    assert ServerPatch().model_fields_set == set()
