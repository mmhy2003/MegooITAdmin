"""How a message leaves: SMTP (the standard library, in a worker thread), an HTTPS POST of JSON, and Telegram's
sendMessage. A failure is a DeliveryFailed with a short code and nothing else: no URL, token, password or text of the
original exception, which is dropped from the chain so a traceback cannot show it either."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any
from urllib.parse import urlsplit

import httpx

TELEGRAM_API = "https://api.telegram.org"
TIMEOUT_SECONDS = 10


class DeliveryFailed(Exception):
    """A message was not delivered. `code` says why, in words safe to store and show."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class EmailConfig:
    host: str
    port: int
    security: str  # "starttls", "tls" or "none"
    username: str
    password: str
    from_name: str
    from_address: str


def _smtp_code(exc: BaseException) -> str:
    # smtplib's errors are OSErrors, and so are ssl's and timeouts: the most specific type goes first.
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "recipients_refused"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "auth_failed"
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "connection_failed"
    if isinstance(exc, smtplib.SMTPException):
        return "smtp_failed"
    return _network_code(exc)


def _network_code(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLError):
        return "tls_failed"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "connection_failed"


def _send_email_now(config: EmailConfig, recipients: list[str], message: EmailMessage) -> None:
    context = ssl.create_default_context()
    if config.security == "tls":
        smtp = smtplib.SMTP_SSL(config.host, config.port, timeout=TIMEOUT_SECONDS, context=context)
    else:
        smtp = smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDS)
    with smtp:
        if config.security == "starttls":
            try:
                smtp.starttls(context=context)
            except smtplib.SMTPNotSupportedError:
                raise DeliveryFailed("tls_failed") from None
        if config.username:
            try:
                smtp.login(config.username, config.password)
            except smtplib.SMTPNotSupportedError:
                raise DeliveryFailed("auth_failed") from None
        # Raises SMTPRecipientsRefused only when every recipient was refused; one accepted address is enough.
        smtp.send_message(message, from_addr=config.from_address, to_addrs=recipients)


async def send_email(config: EmailConfig, recipients: list[str], subject: str, body: str) -> None:
    """Sends one plain-text message. The To header is the from address, and the recipients are only in the envelope,
    as Bcc, so they do not see each other."""
    message = EmailMessage()
    message["From"] = formataddr((config.from_name, config.from_address))
    message["To"] = config.from_address
    message["Subject"] = subject
    message.set_content(body)
    code = None
    try:
        await asyncio.to_thread(_send_email_now, config, recipients, message)
    except DeliveryFailed:
        raise
    except OSError as exc:
        code = _smtp_code(exc)
    if code:
        raise DeliveryFailed(code) from None


def check_url(url: str, allow_http: bool) -> None:
    """A webhook URL must be https://, or http:// when `allow_http` is set (the dev and test stacks only)."""
    try:
        parts = urlsplit(url)
        parts.port  # raises ValueError for a port out of range
    except ValueError:
        raise DeliveryFailed("bad_url") from None
    if parts.scheme == "http" and not allow_http:
        raise DeliveryFailed("webhook_url_https")
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise DeliveryFailed("bad_url")


def _caused_by_tls(exc: BaseException) -> bool:
    # httpx wraps httpcore's error, which wraps ssl's.
    while exc is not None:
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


async def _post(url: str, payload: Any) -> None:
    code = None
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            # A stream, closed unread: the answer's body never comes into the app.
            async with client.stream("POST", url, json=payload) as response:
                status = response.status_code
    except httpx.TimeoutException:
        code = "timeout"
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        code = "bad_url"
    except httpx.TransportError as exc:
        code = "tls_failed" if _caused_by_tls(exc) else "connection_failed"
    if code:
        raise DeliveryFailed(code) from None
    if 300 <= status < 400:
        raise DeliveryFailed("redirect_refused")
    if not 200 <= status < 300:
        raise DeliveryFailed("http_status")


async def post_json(url: str, payload: Any, *, allow_http: bool) -> None:
    """POSTs `payload` as JSON to a webhook. Redirects are not followed, and the try has 10 seconds."""
    check_url(url, allow_http)
    await _post(url, payload)


async def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Sends `text` to a Telegram chat through the bot's sendMessage."""
    await _post(f"{TELEGRAM_API}/bot{token}/sendMessage", {"chat_id": chat_id, "text": text})
