"""python -m app.collector: the collector's process. SIGTERM closes the channels, writes what is buffered and exits.
If the writer or the supervisor ends by itself, the process exits with status 1, so that Compose restarts it."""

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.collector.checks.runner import Recorder
from app.collector.state import StatusBook
from app.collector.stream import Publisher
from app.collector.supervisor import Supervisor
from app.collector.writer import Writer
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.valkey import valkey_client

logger = logging.getLogger("app.collector")

SHUTDOWN_FLUSH = 5.0


async def serve(stop: asyncio.Event) -> None:
    """Runs the writer and the supervisor until `stop` is set, then stops every stream and writes what is buffered.
    Raises when the writer or the supervisor ends before (RuntimeError when it returned)."""
    settings = get_settings()
    status = StatusBook(SessionLocal)
    while not stop.is_set():  # wait for the database, without giving up
        try:
            await status.load()
            break
        except (SQLAlchemyError, OSError) as error:
            logger.warning("Waiting for the database: %s", error)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), 5)
    if stop.is_set():
        return
    try:
        valkey = valkey_client(settings)
    except RuntimeError as error:
        logger.warning("%s Samples are not published.", error)
        valkey = None
    writer = Writer(SessionLocal)
    publisher = Publisher(valkey)
    supervisor = Supervisor(
        sessions=SessionLocal,
        publisher=publisher,
        writer=writer,
        status=status,
        recorder=Recorder(SessionLocal, publisher, writer),
        heartbeat=Path(settings.collector_heartbeat_file),
    )
    tasks = [asyncio.create_task(writer.run()), asyncio.create_task(supervisor.run())]
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait([stopped, *tasks], return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if task.done():
                raise task.exception() or RuntimeError(f"{task.get_coro().__qualname__} returned")
    finally:
        stopped.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await supervisor.stop()
        with suppress(TimeoutError):
            await asyncio.wait_for(writer.flush(), SHUTDOWN_FLUSH)
        if valkey is not None:
            await valkey.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        logger.info("The collector started.")
        await serve(stop)
        logger.info("The collector stopped.")

    try:
        asyncio.run(run())
    except Exception:
        logger.exception("The collector failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
