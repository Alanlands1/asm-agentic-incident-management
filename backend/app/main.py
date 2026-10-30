"""FastAPI Application factory and lifecycle."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.common.config import settings
from app.common.exceptions import global_exception_handler
from app.common.logging import setup_logging
from app.common.middleware import RequestLoggingMiddleware
from app.db.session import SessionLocal, init_db
from app.platform.admin.runtime_config import apply_overrides
from app.routes import api_router

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and shutdown events."""
    setup_logging()
    logger.info(f"Starting {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
    init_db()
    with SessionLocal() as db:
        apply_overrides(db)  # admin changes survive a restart
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}")


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.DEBUG else None,
        docs_url=f"{settings.API_V1_STR}/docs" if settings.DEBUG else None,
        redoc_url=f"{settings.API_V1_STR}/redoc" if settings.DEBUG else None,
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

    return app


app = create_application()
