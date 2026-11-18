"""Global exception handlers."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.exceptions")


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler for unhandled server exceptions."""
    logger.exception(f"Unhandled error processing {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please contact support.",
        },
    )
