"""Optional label-free Prometheus rendering and HTTP serving."""

import asyncio
import hmac
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import BaseModel, ConfigDict, Field

from unifi_mcp.exceptions import UniFiConfigError


class MetricsSnapshot(BaseModel):
    """Fixed aggregate metric values; identity labels are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    runtime_up: int = Field(ge=0)
    events_total: int = Field(ge=0)
    schedules_enabled: int = Field(ge=0)
    webhook_pending: int = Field(ge=0)
    observations_total: int = Field(ge=0)
    controllers_reachable: int = Field(ge=0)
    controllers_unreachable: int = Field(ge=0)


class MetricsState:
    """Thread-safe handoff from async runtime refreshes to the HTTP thread."""

    def __init__(self, snapshot: MetricsSnapshot) -> None:
        self._snapshot = snapshot
        self._lock = threading.Lock()

    def get(self) -> MetricsSnapshot:
        with self._lock:
            return self._snapshot

    def set(self, snapshot: MetricsSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot


def render_prometheus(snapshot: MetricsSnapshot) -> bytes:
    """Render a fresh registry so global application state cannot add labels."""
    try:
        from prometheus_client import CollectorRegistry, Gauge, generate_latest
    except ImportError as exc:
        raise UniFiConfigError(
            "Prometheus support requires the observability extra: install mcp-unifi[observability]"
        ) from exc

    registry = CollectorRegistry()
    metrics = {
        "unifi_mcp_runtime_up": ("Runtime store availability", snapshot.runtime_up),
        "unifi_mcp_events_total": ("Retained normalized events", snapshot.events_total),
        "unifi_mcp_schedules_enabled": (
            "Enabled allowlisted schedules",
            snapshot.schedules_enabled,
        ),
        "unifi_mcp_webhook_pending": (
            "Pending or retryable webhook deliveries",
            snapshot.webhook_pending,
        ),
        "unifi_mcp_observations_total": (
            "Retained aggregate observations",
            snapshot.observations_total,
        ),
        "unifi_mcp_controllers_reachable": (
            "Controllers reachable during the last collection",
            snapshot.controllers_reachable,
        ),
        "unifi_mcp_controllers_unreachable": (
            "Controllers unavailable during the last collection",
            snapshot.controllers_unreachable,
        ),
    }
    for name, (description, value) in metrics.items():
        Gauge(name, description, registry=registry).set(value)
    return generate_latest(registry)


class MetricsServer:
    """Small stoppable metrics listener with optional bearer authentication."""

    def __init__(
        self,
        host: str,
        port: int,
        snapshot_provider: Callable[[], MetricsSnapshot],
        *,
        bearer_token_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._snapshot_provider = snapshot_provider
        self._bearer_token_provider = bearer_token_provider
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._port
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            return
        provider = self._snapshot_provider
        token_provider = self._bearer_token_provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                if token_provider is not None:
                    expected = token_provider()
                    supplied = self.headers.get("Authorization", "")
                    if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
                        self.send_response(401)
                        self.send_header("WWW-Authenticate", "Bearer")
                        self.end_headers()
                        return
                body = render_prometheus(provider())
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="unifi-prometheus",
            daemon=True,
        )
        self._thread.start()

    async def close(self) -> None:
        server = self._server
        thread = self._thread
        if server is None:
            return
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        if thread is not None:
            await asyncio.to_thread(thread.join, 5)
        self._server = None
        self._thread = None
