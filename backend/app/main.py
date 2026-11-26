import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI

from app.alerts.router import alerts_router, server_alerts_router
from app.alerts.router import rules_router as alert_rules_router
from app.auth.router import router as auth_router
from app.checks.router import router as checks_router
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.inventory.router import router as inventory_router
from app.inventory.server_router import router as server_router
from app.metrics.router import router as metrics_router
from app.metrics.socket import router as metrics_socket_router
from app.notify.sender import Sender
from app.users.router import router as users_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.auth_secret_key is None:
        raise RuntimeError(
            "AUTH_SECRET_KEY is not set: the API checks authenticator codes with it. Run make up, or see .env.example"
        )
    # Caddy forwards /api/* unchanged, and nothing is served outside /api, the docs included. The docs are open to
    # anyone who reaches them, so they are served only on request (decision 20).
    docs = settings.api_docs

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The sender delivers the events the collector queues. The tests switch it off (NOTIFICATION_SENDER=false).
        task = None
        if settings.notification_sender:
            task = asyncio.create_task(Sender(SessionLocal, settings=settings).run())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="MegooITAdmin",
        version=settings.app_version,
        openapi_url="/api/openapi.json" if docs else None,
        docs_url="/api/docs" if docs else None,
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect" if docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    # The parent of every route, so a feature cannot forget the prefix: include feature routers into it.
    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        # Liveness only: the entrypoint migrated and set the API role's password before Uvicorn started, so an
        # answer means "migrated and serving".
        return {"status": "ok"}

    api.include_router(auth_router)
    api.include_router(users_router)
    api.include_router(inventory_router)
    api.include_router(server_router)
    api.include_router(checks_router)
    api.include_router(metrics_router)
    api.include_router(metrics_socket_router)
    api.include_router(alert_rules_router)
    api.include_router(alerts_router)
    api.include_router(server_alerts_router)
    app.include_router(api)
    return app


app = create_app()
