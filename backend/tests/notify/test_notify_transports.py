import asyncio
import json
import traceback
from email import message_from_string

import pytest

from app.notify import transports
from app.notify.transports import DeliveryFailed, EmailConfig, check_url, post_json, send_email, send_telegram
from sinks import HttpSink, SmtpSink

TOKEN = "123456:secret-bot-token"


def email_config(port):
    return EmailConfig(
        host="127.0.0.1",
        port=port,
        security="none",
        username="",
        password="",
        from_name="MegooITAdmin",
        from_address="alerts@example.com",
    )


async def test_email_goes_to_every_recipient_in_bcc():
    async with SmtpSink() as smtp:
        await send_email(email_config(smtp.port), ["ann@example.com", "bob@example.com"], "[Critical] db", "Full.")

    [mail] = smtp.mail
    assert mail["from"] == "alerts@example.com"
    assert mail["to"] == ["ann@example.com", "bob@example.com"]
    message = message_from_string(mail["data"])
    assert message["To"] == "alerts@example.com"
    assert message["Cc"] is None and message["Bcc"] is None
    assert "ann@example.com" not in mail["data"] and "bob@example.com" not in mail["data"]
    assert message["From"] == "MegooITAdmin <alerts@example.com>"
    assert message["Subject"] == "[Critical] db"
    assert message.get_payload().strip() == "Full."


async def test_email_counts_as_sent_when_one_recipient_is_accepted():
    async with SmtpSink(refused=["gone@example.com"]) as smtp:
        await send_email(email_config(smtp.port), ["gone@example.com", "bob@example.com"], "Subject", "Body")

    [mail] = smtp.mail
    assert mail["to"] == ["bob@example.com"]


async def test_email_refused_by_all_raises_recipients_refused():
    async with SmtpSink(refused=["gone@example.com"]) as smtp:
        with pytest.raises(DeliveryFailed) as caught:
            await send_email(email_config(smtp.port), ["gone@example.com"], "Subject", "Body")

    assert caught.value.code == "recipients_refused"
    assert smtp.mail == []


async def test_a_webhook_posts_json_and_ignores_the_body():
    async with HttpSink() as sink:
        # The answer announces far more body than it sends: reading it would wait for the 10-second timeout.
        sink.respond_with(200, {"Content-Length": "10000000"}, b"partial")
        await asyncio.wait_for(post_json(f"{sink.url}/hook", {"text": "hello"}, allow_http=True), 3)

    [post] = sink.received
    assert post["path"] == "/hook"
    assert post["headers"]["content-type"] == "application/json"
    assert json.loads(post["body"]) == {"text": "hello"}


async def test_a_redirect_is_not_followed():
    async with HttpSink() as sink:
        sink.respond_with(302, {"Location": f"{sink.url}/elsewhere"})
        with pytest.raises(DeliveryFailed) as caught:
            await post_json(f"{sink.url}/hook", {"text": "hello"}, allow_http=True)

    assert caught.value.code == "redirect_refused"
    assert [post["path"] for post in sink.received] == ["/hook"]


async def test_an_http_url_is_refused_unless_allowed():
    async with HttpSink() as sink:
        with pytest.raises(DeliveryFailed) as caught:
            await post_json(f"{sink.url}/hook", {"text": "hello"}, allow_http=False)
        assert caught.value.code == "webhook_url_https"
        assert sink.received == []

        await post_json(f"{sink.url}/hook", {"text": "hello"}, allow_http=True)
        assert len(sink.received) == 1

    check_url("https://hooks.example.com/x", allow_http=False)
    for url in ["ftp://hooks.example.com/x", "https://", "not a url", "https://host:99999/x"]:
        with pytest.raises(DeliveryFailed) as caught:
            check_url(url, allow_http=True)
        assert caught.value.code == "bad_url", url


async def test_a_non_2xx_answer_is_http_status():
    async with HttpSink() as sink:
        for status in (400, 404, 500):
            sink.respond_with(status)
            with pytest.raises(DeliveryFailed) as caught:
                await post_json(f"{sink.url}/hook", {"text": "hello"}, allow_http=True)
            assert caught.value.code == "http_status"


async def test_telegram_posts_send_message(monkeypatch):
    async with HttpSink() as sink:
        monkeypatch.setattr(transports, "TELEGRAM_API", sink.url)
        await send_telegram(TOKEN, "-100200", "Critical: db-prod-01: /var is 93.4% full.")

    [post] = sink.received
    assert post["path"] == f"/bot{TOKEN}/sendMessage"
    assert json.loads(post["body"]) == {"chat_id": "-100200", "text": "Critical: db-prod-01: /var is 93.4% full."}


def _told(error):
    """What an error says, and every exception a traceback would show with it (the source lines aside, which are this
    file's)."""
    told, exception = [], error
    while exception is not None:
        told.extend([*traceback.format_exception_only(exception), repr(exception), str(exception.args)])
        exception = exception.__cause__ or (None if exception.__suppress_context__ else exception.__context__)
    return " ".join(told)


async def test_no_error_holds_the_url_or_the_token(monkeypatch, unused_tcp_port):
    url = f"http://127.0.0.1:{unused_tcp_port}/hook/path-secret"
    errors = []
    with pytest.raises(DeliveryFailed) as caught:
        await post_json(url, {"text": "hello"}, allow_http=True)
    assert caught.value.code == "connection_failed"
    errors.append(caught.value)

    monkeypatch.setattr(transports, "TELEGRAM_API", f"http://127.0.0.1:{unused_tcp_port}")
    with pytest.raises(DeliveryFailed) as caught:
        await send_telegram(TOKEN, "-100200", "text")
    errors.append(caught.value)

    async with HttpSink() as sink:
        sink.respond_with(500)
        with pytest.raises(DeliveryFailed) as caught:
            await post_json(f"{sink.url}/hook/path-secret", {"text": "hello"}, allow_http=True)
        errors.append(caught.value)
        monkeypatch.setattr(transports, "TELEGRAM_API", sink.url)
        with pytest.raises(DeliveryFailed) as caught:
            await send_telegram(TOKEN, "-100200", "text")
        errors.append(caught.value)

    with pytest.raises(DeliveryFailed) as caught:
        await post_json("https://host:99999/path-secret", {}, allow_http=False)
    errors.append(caught.value)

    config = email_config(unused_tcp_port)
    config.username, config.password = "smtp-user", "smtp-password-secret"
    with pytest.raises(DeliveryFailed) as caught:
        await send_email(config, ["ann@example.com"], "Subject", "Body")
    assert caught.value.code == "connection_failed"
    errors.append(caught.value)

    for error in errors:
        told = _told(error)
        for secret in ("path-secret", "secret-bot-token", "smtp-password-secret"):
            assert secret not in told
