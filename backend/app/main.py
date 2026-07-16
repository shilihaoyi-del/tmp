"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.metrics_routes import router as metrics_router
from app.api.routes import router
from app.config import get_settings
from app.mqtt.client import mqtt_bridge
from app.services.arm_state import arm_state
from app.services.simulator import hardware_simulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("arm-backend")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s on port %s", settings.app_name, settings.app_port)
    await mqtt_bridge.start()
    if settings.enable_simulator:
        arm_state.set_source(settings.sim_source_label.lower())
        await hardware_simulator.start()
        logger.info("Simulator ON — no real SC171V2 hardware required")
    yield
    if settings.enable_simulator:
        await hardware_simulator.stop()
    await mqtt_bridge.stop()
    logger.info("Backend stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")

    if FRONTEND_DIST.is_dir():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            candidate = FRONTEND_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

        logger.info("Serving frontend from %s", FRONTEND_DIST)

    return app


app = create_app()
