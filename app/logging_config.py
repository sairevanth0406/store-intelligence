"""
Structured logging with structlog + trace ID middleware.
Purplle Store Intelligence System.
"""
import uuid
import time
import structlog
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def setup_logging():
    """Configure structlog for JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Attach a trace_id to every request and log latency."""

    async def dispatch(self, request: Request, call_next):
        trace_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )
        t0 = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        structlog.get_logger().info(
            "request.complete",
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        response.headers["X-Trace-ID"] = trace_id
        return response
