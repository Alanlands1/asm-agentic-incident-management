"""FastAPI Application factory and lifecycle."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.runtime_config import apply_overrides
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import global_exception_handler
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware
from app.core.telemetry import setup_telemetry, shutdown_telemetry
from app.db.session import AsyncSessionLocal, close_db
from app.services import confluence, jira

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and shutdown events."""
    setup_logging()
    logger.info(f"Starting {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
    async with AsyncSessionLocal() as db:
        await db.run_sync(apply_overrides)  # admin changes survive a restart
    # Always running: each loop reads its interval every minute, so an admin can turn a sync on or off without a restart
    schedulers = [asyncio.create_task(loop(AsyncSessionLocal)) for loop in (jira.schedule_loop, confluence.schedule_loop)]
    try:
        yield
    finally:
        for task in schedulers:
            task.cancel()
        logger.info(f"Shutting down {settings.PROJECT_NAME}")
        shutdown_telemetry()
        await close_db()


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS Middleware
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Custom Logging & Request Tracking Middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Exception Handlers
    app.add_exception_handler(Exception, global_exception_handler)

    # Routers
    app.include_router(api_router, prefix=settings.API_V1_STR)

    # Request tracing to Phoenix (no-op unless PHOENIX_ENABLED); instruments the app after all routes are added
    setup_telemetry(app)

    return app


app = create_application()
