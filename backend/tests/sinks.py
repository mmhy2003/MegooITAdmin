"""Local stand-ins for the outside world of notifications: an HTTP sink that records the POSTs it gets (webhooks and
Telegram) and a minimal SMTP sink that records the mail it gets. Standard library only, so the stacks run this file as
a script in a plain Python image: `python sinks.py` serves HTTP on 0.0.0.0:8080 and SMTP on 0.0.0.0:2525, and
`GET /received` on the HTTP port tells what both have received."""

import asyncio
import json


class _Server:
    """An asyncio TCP server that closes its open connections when it stops."""

    def __init__(self, host, port):
        self._host, self._port = host, port
        self._server = None
        self._writers = set()
        self.port = None

    async def start(self):
        self._server = await asyncio.start_server(self._serve, self._host, self._port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        await self._server.wait_closed()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.stop()

    async def _serve(self, reader, writer):
        self._writers.add(writer)
        try:
            await self.handle(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def handle(self, reader, writer):
        raise NotImplementedError


class SmtpSink(_Server):
    """Answers EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP and QUIT, without TLS or AUTH. An address in `refused` gets 550
    at RCPT. Each message is recorded as {"from", "to" (the accepted addresses), "data" (the text after DATA)}."""

    def __init__(self, host="127.0.0.1", port=0, refused=()):
        super().__init__(host, port)
        self.refused = {address.lower() for address in refused}
        self.mail = []

    async def handle(self, reader, writer):
        async def reply(line):
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        await reply("220 sink ESMTP")
        sender, recipients = None, []
        while line := await reader.readline():
            command = line.decode("utf-8", "replace").rstrip("\r\n")
            verb = command[:4].upper()
            if verb == "EHLO":
                await reply("250-sink\r\n250 8BITMIME")
            elif verb == "HELO":
                await reply("250 sink")
            elif verb == "MAIL":
                sender, recipients = _address(command), []
                await reply("250 OK")
            elif verb == "RCPT":
                address = _address(command)
                if address.lower() in self.refused:
                    await reply("550 No such user")
                else:
                    recipients.append(address)
                    await reply("250 OK")
            elif verb == "DATA":
                await reply("354 End data with <CR><LF>.<CR><LF>")
                lines = []
                while (data := await reader.readline()) not in (b".\r\n", b".\n", b""):
                    lines.append(data[1:] if data.startswith(b"..") else data)
                self.mail.append({"from": sender, "to": recipients, "data": b"".join(lines).decode("utf-8", "replace")})
                sender, recipients = None, []
                await reply("250 OK")
            elif verb == "RSET":
                sender, recipients = None, []
                await reply("250 OK")
            elif verb == "NOOP":
                await reply("250 OK")
            elif verb == "QUIT":
                await reply("221 Bye")
                return
            else:
                await reply("502 Command not implemented")


def _address(command):
    """The address between < and > of a MAIL FROM or RCPT TO command."""
    start = command.find("<")
    return command[start + 1 : command.find(">", start)] if start >= 0 else ""


class HttpSink(_Server):
    """Records each POST as {"path", "headers" (lowercased names), "body" (text)} and answers `respond_with`'s status,
    headers and body (204 by default). `GET /received` gives {"webhooks": [...], "mail": [...]}, the mail being that
    of the SMTP sink it was given; any other GET is 404. Each connection serves one request, and the sink keeps it
    open until the client closes it, so a client that waits for more body than it was sent hangs."""

    def __init__(self, host="127.0.0.1", port=0, mail=None):
        super().__init__(host, port)
        self.mail_sink = mail
        self.received = []
        self.respond_with(204)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def respond_with(self, status, headers=None, body=b""):
        self._answer = (status, dict(headers or {}), body)

    async def handle(self, reader, writer):
        request_line = (await reader.readline()).decode("latin-1").split()
        if len(request_line) < 2:
            return
        method, path = request_line[0], request_line[1]
        headers = {}
        while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        body = await reader.readexactly(int(headers.get("content-length", "0")))
        if method == "POST":
            self.received.append({"path": path, "headers": headers, "body": body.decode("utf-8", "replace")})
            status, answer_headers, answer = self._answer
        elif method == "GET" and path == "/received":
            mail = self.mail_sink.mail if self.mail_sink else []
            status, answer_headers = 200, {"Content-Type": "application/json"}
            answer = json.dumps({"webhooks": self.received, "mail": mail}).encode()
        else:
            status, answer_headers, answer = 404, {}, b""
        answer_headers = {"Content-Length": str(len(answer)), "Connection": "close", **answer_headers}
        head = f"HTTP/1.1 {status} Sink\r\n" + "".join(f"{k}: {v}\r\n" for k, v in answer_headers.items()) + "\r\n"
        writer.write(head.encode("latin-1") + answer)
        await writer.drain()
        await reader.read()


async def main():
    mail = await SmtpSink("0.0.0.0", 2525).start()
    await HttpSink("0.0.0.0", 8080, mail=mail).start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
