from fastapi import APIRouter, FastAPI

from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.users.router import router as users_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Caddy forwards /api/* unchanged, and nothing is served outside /api, the docs included. The docs are open to
    # anyone who reaches them, so they are served only on request (decision 20).
    docs = settings.api_docs
    app = FastAPI(
        title="MegooITAdmin",
        version=settings.app_version,
        openapi_url="/api/openapi.json" if docs else None,
        docs_url="/api/docs" if docs else None,
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect" if docs else None,
        redoc_url=None,
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
    app.include_router(api)
    return app


app = create_app()
