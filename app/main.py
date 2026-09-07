"""FunnelIQ API entry point.

One FastAPI service serves both the JSON API (/api/*, /health) and the static
dashboard (/static/*). Run locally with:

    uvicorn app.main:app --reload
"""

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import insights, predict, records, simulate
from ml.registry import ModelRegistry

APP_VERSION = "0.7.0"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_started_at = time.time()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FunnelIQ", version=APP_VERSION, docs_url="/api/docs", redoc_url=None)
    app.state.registry = ModelRegistry.load(settings.models_dir)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        """Liveness endpoint used by Railway's healthcheck and by scripts/gate.py."""
        return {
            "status": "ok",
            "version": APP_VERSION,
            "commit": (settings.railway_git_commit_sha or "dev")[:12],
            "env": settings.app_env,
            "supabase_configured": bool(settings.supabase_url and settings.supabase_anon_key),
            "models_loaded": app.state.registry.loaded,
            "uptime_s": round(time.time() - _started_at, 1),
        }

    @app.get("/api/config", tags=["ops"])
    def public_config() -> dict:
        """Public values the browser needs to start the Supabase login flow.

        The anon key is public by design (it is shipped to every browser);
        Row Level Security is what protects the data.
        """
        return {"supabase_url": settings.supabase_url, "supabase_anon_key": settings.supabase_anon_key}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/static/dashboard.html")

    app.include_router(records.router)
    app.include_router(insights.router)
    app.include_router(predict.router)
    app.include_router(simulate.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
