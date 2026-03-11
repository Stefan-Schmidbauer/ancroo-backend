"""Ancroo Backend - FastAPI Application."""

import logging
import os
import re
import time
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.version import get_version_info
from src.api.v1.router import api_router
from src.admin.routes import router as admin_router
from src.db.session import init_db

# Configure application logging — without this, all src.* loggers are silent
# because uvicorn only sets up its own loggers, not the root logger.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

logger = logging.getLogger(__name__)


def _cleanup_stale_uploads(upload_dir: str, max_age_seconds: int = 3600) -> None:
    """Remove upload temp files older than max_age_seconds."""
    if not os.path.isdir(upload_dir):
        return
    now = time.time()
    for filename in os.listdir(upload_dir):
        filepath = os.path.join(upload_dir, filename)
        if os.path.isfile(filepath):
            age = now - os.path.getmtime(filepath)
            if age > max_age_seconds:
                os.unlink(filepath)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    await init_db()
    os.makedirs(settings.upload_temp_dir, exist_ok=True)
    _cleanup_stale_uploads(settings.upload_temp_dir)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    version_info = get_version_info()

    app = FastAPI(
        title=settings.app_name,
        description="Ancroo — AI Workflow Runner for your Browser",
        version=version_info["version"],
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        swagger_ui_parameters={"defaultModelsExpandDepth": -1},
        swagger_favicon_url="/static/favicon.png",
    )

    # Build extension CORS regex: restrict to known IDs if configured,
    # otherwise allow all extensions (development mode)
    if settings.cors_extension_ids:
        ids = "|".join(re.escape(eid) for eid in settings.cors_extension_ids)
        extension_regex = f"^chrome-extension://({ids})$"
    else:
        extension_regex = r"^chrome-extension://.*$"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=extension_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve workflow demo pages as static files (if configured)
    if settings.workflows_dir:
        workflows_path = Path(settings.workflows_dir)
        if workflows_path.is_dir():
            app.mount("/demos", StaticFiles(directory=str(workflows_path)), name="demos")

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(admin_router)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": version_info["version"],
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
