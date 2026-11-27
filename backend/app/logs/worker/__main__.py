"""python -m app.logs.worker: the logs worker's process. SIGTERM closes every source's channel and exits.
If the hub ends by itself, a Valkey error for one, the process exits with status 1, so that Compose restarts it."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.valkey import valkey_client
from app.logs.worker.hub import Hub
from app.logs.worker.source import Limits

logger = logging.getLogger("app.logs.worker")


async def serve(stop: asyncio.Event) -> None:
    """Runs the hub until `stop` is set, then stops every source. Raises the error that ended the hub when it ends
    before (RuntimeError when it returned). Without VALKEY_URL it raises RuntimeError: the worker needs Valkey."""
    settings = get_settings()
    valkey = valkey_client(settings)
    hub = Hub(SessionLocal, valkey, limits=Limits(max_lines_per_second=settings.log_stream_max_lines_per_second))
    task = asyncio.create_task(hub.run(Path(settings.logs_heartbeat_file)))
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait([stopped, task], return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            error = task.exception() or RuntimeError("Hub.run returned")
            while isinstance(error, BaseExceptionGroup):  # the hub's task group: raise the error that ended it
                error = error.exceptions[0]
            raise error
    finally:
        stopped.cancel()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await hub.stop()
        await valkey.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        logger.info("The logs worker started.")
        await serve(stop)
        logger.info("The logs worker stopped.")

    try:
        asyncio.run(run())
    except Exception:
        logger.exception("The logs worker failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
