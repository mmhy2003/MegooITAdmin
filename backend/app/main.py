from fastapi import APIRouter, FastAPI

from app.core.config import get_settings


def create_app() -> FastAPI:
    # Caddy forwards /api/* unchanged, and nothing is served outside /api, the docs included.
    app = FastAPI(
        title="MegooITAdmin",
        version=get_settings().app_version,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        redoc_url=None,
    )
    # The parent of every route, so a feature cannot forget the prefix: include feature routers into it.
    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        # Liveness only: the entrypoint migrated before Uvicorn started, so an answer means "migrated and serving".
        return {"status": "ok"}

    app.include_router(api)
    return app


app = create_app()
