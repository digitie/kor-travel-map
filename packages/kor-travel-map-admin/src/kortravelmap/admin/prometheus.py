"""Prometheus metrics for the kor-travel-map API/admin package.

Prometheus uses a pull model. The API exposes ``/metrics`` on the same
FastAPI port and the external observability stack scrapes it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import perf_counter

from fastapi import Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from starlette.responses import Response
from starlette.routing import Match

__all__ = ["PrometheusMetrics", "RequestMetricLabels", "current_request_metric_labels"]

_HTTP_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
_HTTP_RESPONSE_SIZE_BUCKETS: tuple[float, ...] = (
    100.0,
    1_000.0,
    10_000.0,
    100_000.0,
    1_000_000.0,
    5_000_000.0,
    10_000_000.0,
)
_DB_DURATION_BUCKETS: tuple[float, ...] = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)
_UNMATCHED_ROUTE = "__unmatched__"
_UNKNOWN_ROUTE = "__unknown__"
_UNKNOWN_SURFACE = "unknown"
_REQUEST_LABELS: ContextVar[RequestMetricLabels | None] = ContextVar(
    "kor_travel_map_request_metric_labels",
    default=None,
)


@dataclass(frozen=True, slots=True)
class RequestMetricLabels:
    """Low-cardinality labels shared by HTTP and downstream dependency metrics."""

    method: str
    path: str
    surface: str


def current_request_metric_labels() -> RequestMetricLabels | None:
    """Return current request labels for DB/outbound instrumentation."""
    return _REQUEST_LABELS.get()


class PrometheusMetrics:
    """Small per-app Prometheus registry and HTTP request instrumenter."""

    def __init__(self, *, service_name: str, version: str) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        ProcessCollector(registry=self.registry)

        self.requests_total = Counter(
            "kor_travel_map_http_requests_total",
            "Total HTTP requests handled by kor-travel-map.",
            ("method", "path", "surface", "status_code"),
            registry=self.registry,
        )
        self.request_duration_seconds = Histogram(
            "kor_travel_map_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "path", "surface", "status_code"),
            buckets=_HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.requests_in_progress = Gauge(
            "kor_travel_map_http_requests_in_progress",
            "HTTP requests currently being handled.",
            ("method", "surface"),
            registry=self.registry,
        )
        self.response_size_bytes = Histogram(
            "kor_travel_map_http_response_size_bytes",
            "HTTP response body size in bytes when Content-Length is known.",
            ("method", "path", "surface", "status_code"),
            buckets=_HTTP_RESPONSE_SIZE_BUCKETS,
            registry=self.registry,
        )
        self.request_exceptions_total = Counter(
            "kor_travel_map_http_request_exceptions_total",
            "Unhandled HTTP request exceptions by route.",
            ("method", "path", "surface", "exception_type"),
            registry=self.registry,
        )
        self.db_queries_total = Counter(
            "kor_travel_map_db_queries_total",
            "SQL queries executed by the kor-travel-map API.",
            ("path", "surface", "operation", "status"),
            registry=self.registry,
        )
        self.db_query_duration_seconds = Histogram(
            "kor_travel_map_db_query_duration_seconds",
            "SQL query duration in seconds for the kor-travel-map API.",
            ("path", "surface", "operation", "status"),
            buckets=_DB_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.app_info = Gauge(
            "kor_travel_map_app_info",
            "kor-travel-map application metadata.",
            ("service", "version"),
            registry=self.registry,
        )
        self.app_info.labels(service=service_name, version=version).set(1)

    async def instrument_request(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Record count, in-flight gauge and latency for one HTTP request."""
        started_at = perf_counter()
        method = request.method
        labels = RequestMetricLabels(
            method=method,
            path=_route_path(request),
            surface=_route_surface(request.url.path),
        )
        token = _set_request_metric_labels(labels)
        in_progress = self.requests_in_progress.labels(
            method=labels.method,
            surface=labels.surface,
        )
        in_progress.inc()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            self.request_exceptions_total.labels(
                method=labels.method,
                path=labels.path,
                surface=labels.surface,
                exception_type=type(exc).__name__,
            ).inc()
            raise
        finally:
            duration_seconds = max(0.0, perf_counter() - started_at)
            status = str(status_code)
            self.requests_total.labels(
                method=labels.method,
                path=labels.path,
                surface=labels.surface,
                status_code=status,
            ).inc()
            self.request_duration_seconds.labels(
                method=labels.method,
                path=labels.path,
                surface=labels.surface,
                status_code=status,
            ).observe(duration_seconds)
            response_size = _response_size_bytes(response)
            if response_size is not None:
                self.response_size_bytes.labels(
                    method=labels.method,
                    path=labels.path,
                    surface=labels.surface,
                    status_code=status,
                ).observe(response_size)
            in_progress.dec()
            _reset_request_metric_labels(token)

    def observe_db_query(
        self,
        *,
        statement: str,
        duration_seconds: float,
        status: str,
    ) -> None:
        """Record one SQL execution using current request labels if available."""
        labels = current_request_metric_labels()
        path = labels.path if labels is not None else _UNKNOWN_ROUTE
        surface = labels.surface if labels is not None else _UNKNOWN_SURFACE
        operation = _sql_operation(statement)
        self.db_queries_total.labels(
            path=path,
            surface=surface,
            operation=operation,
            status=status,
        ).inc()
        self.db_query_duration_seconds.labels(
            path=path,
            surface=surface,
            operation=operation,
            status=status,
        ).observe(max(0.0, duration_seconds))

    def response(self) -> Response:
        """Return the current registry in Prometheus exposition format."""
        return Response(
            content=generate_latest(self.registry),
            media_type=CONTENT_TYPE_LATEST,
        )


def _set_request_metric_labels(
    labels: RequestMetricLabels,
) -> Token[RequestMetricLabels | None]:
    return _REQUEST_LABELS.set(labels)


def _reset_request_metric_labels(token: Token[RequestMetricLabels | None]) -> None:
    _REQUEST_LABELS.reset(token)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    for candidate in request.app.routes:
        match, _child_scope = candidate.matches(request.scope)
        if match is Match.FULL:
            candidate_path = getattr(candidate, "path", None)
            if isinstance(candidate_path, str) and candidate_path:
                return candidate_path
    return _UNMATCHED_ROUTE


def _route_surface(raw_path: str) -> str:
    parts = [part for part in raw_path.split("/") if part]
    if parts and parts[0] == "v1":
        parts = parts[1:]
    if not parts:
        return "system"
    root = parts[0]
    if root in {"health", "version"}:
        return "system"
    if root == "admin":
        return "admin"
    if root == "ops":
        return "ops"
    if root == "debug":
        return "debug"
    if root in {"categories", "curated-features", "features", "providers", "public"}:
        return "public"
    return "other"


def _response_size_bytes(response: Response | None) -> float | None:
    if response is None:
        return None
    raw_value = response.headers.get("content-length")
    if raw_value is None:
        return None
    try:
        return float(int(raw_value))
    except ValueError:
        return None


def _sql_operation(statement: str) -> str:
    stripped = statement.lstrip()
    if not stripped:
        return "unknown"
    token = stripped.split(None, 1)[0].upper()
    if token in {"DELETE", "INSERT", "SELECT", "UPDATE"}:
        return token.lower()
    if token in {"WITH"}:
        return "with"
    if token in {"CREATE", "ALTER", "DROP", "TRUNCATE"}:
        return "ddl"
    return "other"
