"""HTTP and execution timing middleware."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that injects request IDs and logs latency/status code."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        response: Response = await call_next(request)

        process_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(process_time_ms)

        logger.info(
            f"request_id={request_id} method={request.method} path={request.url.path} "
            f"status={response.status_code} latency_ms={process_time_ms}"
        )
        return response
