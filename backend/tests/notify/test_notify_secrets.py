"""A secret is write-only: once saved, no route answer, audit event, log record or delivery error holds it."""

import logging
from datetime import UTC, datetime

import pytest
from alerts_helpers import make_alert, make_rule
from auth_helpers import audit_rows, make_group, make_server, signed_in
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.notify import transports
from app.notify.models import NotificationDelivery
from app.notify.sender import Sender
from conftest import owner_session
from sinks import HttpSink

pytestmark = pytest.mark.usefixtures("clean_alerts")

PASSWORD = "smtp-password-0451"
PATH_TOKEN = "path-token-9f3c2a"
BOT_TOKEN = "987654:BotTokenSecretABCDEFGHIJKLMNOPQRSTU"
SECRETS = (PASSWORD, PATH_TOKEN, BOT_TOKEN)


async def test_no_answer_audit_event_log_record_or_last_error_holds_a_secret(
    api, clock, monkeypatch, caplog, unused_tcp_port
):
    settings = get_settings().model_copy(update={"webhook_allow_http": True})
    monkeypatch.setattr("app.notify.service.get_settings", lambda: settings)
    # Every send fails: nothing listens on the port, or the sink refuses (httpx logs each request it gets an answer
    # to, with its address).
    nowhere = f"http://127.0.0.1:{unused_tcp_port}"
    refusing = await HttpSink().start()
    refusing.respond_with(403)
    monkeypatch.setattr(transports, "TELEGRAM_API", refusing.url)
    url = f"{nowhere}/hooks/{PATH_TOKEN}"
    email = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": unused_tcp_port,
        "security": "none",
        "username": "alerts",
        "password": PASSWORD,
        "from_address": "alerts@example.com",
    }
    answers = []
    with caplog.at_level(logging.DEBUG):
        async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
            answers.append(await client.put("/api/notifications/email", json=email))
            answers.append(await client.put("/api/notifications/email", json=email | {"password": PASSWORD + "2"}))
            answers.append(await client.get("/api/notifications/email"))
            answers.append(await client.post("/api/notifications/email/test"))
            webhook = await client.post(
                "/api/notification-channels", json={"name": "Hook", "kind": "webhook_json", "url": url}
            )
            slack = await client.post(
                "/api/notification-channels",
                json={"name": "Slack", "kind": "webhook_slack", "url": f"{refusing.url}/{PATH_TOKEN}"},
            )
            telegram = await client.post(
                "/api/notification-channels",
                json={"name": "Chat", "kind": "telegram", "bot_token": BOT_TOKEN, "chat_id": "-100200"},
            )
            answers += [webhook, slack, telegram]
            hook_id, chat_id = webhook.json()["id"], telegram.json()["id"]
            answers.append(await client.patch(f"/api/notification-channels/{hook_id}", json={"url": url + "/v2"}))
            answers.append(
                await client.patch(f"/api/notification-channels/{chat_id}", json={"bot_token": BOT_TOKEN + "x"})
            )
            # Refused changes answer with a code, not the value sent.
            answers.append(
                await client.patch(f"/api/notification-channels/{hook_id}", json={"url": f"ftp://{PATH_TOKEN}"})
            )
            answers.append(
                await client.patch(f"/api/notification-channels/{chat_id}", json={"bot_token": PATH_TOKEN})
            )
            answers.append(await client.get("/api/notification-channels"))
            for channel_id in (hook_id, slack.json()["id"], chat_id):
                answers.append(await client.post(f"/api/notification-channels/{channel_id}/test"))

            server = await make_server((await make_group("Production")).id, "db-prod-01")
            await make_alert(server.id, fired_at=datetime.now(UTC), rule=await make_rule())
            sender = Sender(SessionLocal, settings=settings)
            await sender.dispatch()
            assert await sender.send_due() == 4
            async with owner_session() as session:
                errors = (await session.scalars(select(NotificationDelivery.last_error))).all()
            answers.append(await client.get("/api/notification-channels"))
            answers.append(await client.get("/api/notifications/email"))
            answers.append(await client.delete(f"/api/notification-channels/{hook_id}"))
    await refusing.stop()

    assert [r.status_code for r in answers] == [200] * 9 + [422, 422] + [200] * 6 + [204]
    assert sorted(errors) == ["connection_failed"] * 2 + ["http_status"] * 2
    assert len(refusing.received) == 4
    texts = (
        [r.text for r in answers]
        + await audit_rows()
        + [str(error) for error in errors]
        + [record.getMessage() for record in caplog.records]
        + [caplog.text]
    )
    for secret in SECRETS:
        assert not [text for text in texts if secret in text], secret
