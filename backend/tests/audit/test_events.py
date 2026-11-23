import pytest
from pydantic import ValidationError

from app.audit import Actor, ActorType, Event, Person, Result, RiskClass, Source, Target, changes

ALICE = Actor.human(7, "Alice")


def test_an_action_without_a_dot_is_refused():
    with pytest.raises(ValidationError):
        Event(action="created", actor=ALICE)


def test_an_action_with_upper_case_is_refused():
    with pytest.raises(ValidationError):
        Event(action="Server.created", actor=ALICE)


def test_a_dotted_lower_case_action_is_accepted():
    assert Event(action="auth.sign_in_failed", actor=ALICE).action == "auth.sign_in_failed"


def test_a_float_in_change_is_refused():
    with pytest.raises(ValidationError):
        Event(action="server.updated", actor=ALICE, change={"cpu": {"before": 1.5, "after": 2}})


def test_a_float_nested_in_result_detail_is_refused():
    with pytest.raises(ValidationError):
        Event(action="execution.finished", actor=ALICE, result_detail={"runs": [{"seconds": 0.25}]})


def test_actor_details_must_be_json():
    with pytest.raises(ValidationError):
        Actor(type=ActorType.SYSTEM, name="scheduler", details={"started": object()})


def test_actor_human_agent_and_system_fill_type_id_name_and_details():
    assert ALICE == Actor(type=ActorType.HUMAN, id="7", name="Alice", details={})
    assert Actor.agent(42, "ops", "claude-opus-5-5") == Actor(
        type=ActorType.AGENT,
        id="42",
        name="ops",
        details={"session": "42", "profile": "ops", "model": "claude-opus-5-5"},
    )
    assert Actor.system("collector") == Actor(type=ActorType.SYSTEM, id=None, name="collector", details={})


def test_source_normalises_the_ip_and_cuts_the_user_agent():
    source = Source(ip="2001:DB8::1", user_agent="x" * 2000)
    assert source.ip == "2001:db8::1"
    assert source.user_agent == "x" * 1024
    with pytest.raises(ValidationError):
        Source(ip="not-an-ip")


def test_columns_holds_every_field_as_plain_values():
    event = Event(
        action="server.created",
        actor=Actor.agent("s-1", "ops", "claude-opus-5-5"),
        result=Result.FAILURE,
        target=Target(type="server", id="12", name="db-01"),
        on_behalf_of=Person(id="7", name="Alice"),
        context={"agent_session_id": "s-1"},
        source=Source(ip="203.0.113.9", user_agent="curl/8", auth_method="password", mfa=True),
        reason="new database",
        change={"name": {"before": None, "after": "db-01"}},
        result_detail={"error": "host unreachable"},
        risk_class=RiskClass.CHANGE,
    )
    columns = event.columns()
    assert columns == {
        "actor_type": "agent",
        "actor_id": "s-1",
        "actor_name": "ops",
        "actor_details": {"session": "s-1", "profile": "ops", "model": "claude-opus-5-5"},
        "on_behalf_of_id": "7",
        "on_behalf_of_name": "Alice",
        "action": "server.created",
        "target_type": "server",
        "target_id": "12",
        "target_name": "db-01",
        "context": {"agent_session_id": "s-1"},
        "source_ip": "203.0.113.9",
        "user_agent": "curl/8",
        "auth_method": "password",
        "mfa": True,
        "reason": "new database",
        "change": {"name": {"before": None, "after": "db-01"}},
        "result": "failure",
        "result_detail": {"error": "host unreachable"},
        "risk_class": "change",
    }
    assert type(columns["actor_type"]) is str
    assert type(columns["result"]) is str
    assert type(columns["risk_class"]) is str

    minimal = Event(action="server.created", actor=ALICE).columns()
    assert len(minimal) == 20
    assert minimal["target_type"] is None
    assert minimal["source_ip"] is None
    assert minimal["context"] == {}
    assert minimal["result"] == "success"
    assert type(minimal["result"]) is str
    assert minimal["risk_class"] is None


def test_changes_lists_only_differing_fields():
    before = {"name": "db-01", "port": 22, "group": "prod"}
    after = {"name": "db-02", "port": 22, "group": "prod"}
    assert changes(before, after) == {"name": {"before": "db-01", "after": "db-02"}}


def test_changes_redacts_named_and_password_like_fields():
    before = {"pin": "1234", "db_password": "a", "api_token": "b", "client_secret": "c", "name": "x"}
    after = {"pin": "4321", "db_password": "A", "api_token": "B", "client_secret": "C", "name": "y"}
    redacted = {"before": "[redacted]", "after": "[redacted]"}
    assert changes(before, after, secret={"pin"}) == {
        "api_token": redacted,
        "client_secret": redacted,
        "db_password": redacted,
        "name": {"before": "x", "after": "y"},
        "pin": redacted,
    }


def test_changes_returns_none_when_nothing_differs():
    assert changes({"name": "db-01"}, {"name": "db-01"}) is None


def test_changes_reports_a_field_present_on_one_side_only():
    assert changes({"old": 1}, {"new": 2}) == {
        "new": {"before": None, "after": 2},
        "old": {"before": 1, "after": None},
    }
