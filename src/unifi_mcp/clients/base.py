"""Base HTTP client and lifespan management for UniFi MCP Server."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping, MutableMapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

import httpx
from cachetools import TTLCache
from mcp.server.mcpserver import MCPServer
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from unifi_mcp.auth.local import UniFiCloudAuth, UniFiLocalAuth
from unifi_mcp.config import UniFiDevice, UniFiSettings, settings
from unifi_mcp.exceptions import (
    UniFiAPIError,
    UniFiAuthError,
    UniFiConfigError,
    UniFiConnectionError,
    UniFiRateLimitError,
)
from unifi_mcp.runtime import RuntimeStore

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Application context with shared resources.

    This context is created during server startup and made available
    to all tool handlers via the request context.
    """

    client: httpx.AsyncClient
    settings: UniFiSettings
    cache: MutableMapping[tuple[Any, ...], Any]
    auth: UniFiLocalAuth | UniFiCloudAuth | None = field(default=None)
    runtime: RuntimeStore | None = field(default=None)
    runtime_services: Any | None = field(default=None)
    cache_generation: int = 0


class UniFiHTTPClient:
    """Base HTTP client for UniFi API requests.

    Provides retry logic, authentication handling, and error processing.

    Supports per-device targeting: when constructed with an explicit
    ``device``, requests are sent to that device's Integration API using
    its own API key. Otherwise the legacy/global configuration is used.
    """

    def __init__(self, ctx: AppContext, device: UniFiDevice | None = None):
        """Initialize the HTTP client.

        Args:
            ctx: Application context with shared resources
            device: Optional specific device to target. If provided,
                requests use the device's URL and API key.
        """
        self.ctx = ctx
        self.device = device

    @staticmethod
    def _normalize_cache_value(value: Any) -> Any:
        """Convert request arguments into stable, hashable cache-key values."""
        if isinstance(value, Mapping):
            return tuple(
                sorted(
                    (str(key), UniFiHTTPClient._normalize_cache_value(item))
                    for key, item in value.items()
                )
            )
        if isinstance(value, (list, tuple)):
            return tuple(UniFiHTTPClient._normalize_cache_value(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted(UniFiHTTPClient._normalize_cache_value(item) for item in value))
        try:
            hash(value)
        except TypeError:
            return repr(value)
        return value

    @property
    def _base_url(self) -> str:
        """Get the base URL for API requests."""
        if self.device is not None and self.ctx.settings.mode == "local":
            base = self.device.url.rstrip("/")
            if self.ctx.settings.is_udm:
                return f"{base}/proxy/network"
            return base
        if self.device is not None:
            return self.device.network_api_base
        return self.ctx.settings.api_base_url

    @property
    def _headers(self) -> dict[str, str]:
        """Get headers for requests."""
        if self.device is not None and self.ctx.settings.mode != "local":
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-KEY": self.device.api_key,
            }
        if self.ctx.auth is not None:
            return self.ctx.auth.get_request_headers()
        raise UniFiAuthError("No authentication configured")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _make_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional arguments passed to httpx

        Returns:
            HTTP response

        Raises:
            UniFiConnectionError: If connection fails after retries
            UniFiAuthError: If authentication fails
            UniFiRateLimitError: If rate limited
            UniFiAPIError: For other API errors
        """
        try:
            response = await self.ctx.client.request(
                method,
                url,
                headers=self._headers,
                **kwargs,
            )
        except httpx.ConnectError as e:
            raise UniFiConnectionError(f"Failed to connect: {e}") from e
        except httpx.TimeoutException as e:
            raise UniFiConnectionError(f"Request timed out: {e}") from e

        return response

    async def request(
        self,
        method: str,
        endpoint: str,
        _no_cache: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated API request.

        Args:
            method: HTTP method
            endpoint: API endpoint (will be appended to base URL)
            _no_cache: Skip the read cache (used for cache-busting)
            **kwargs: Additional arguments (json, params, etc.)

        Returns:
            Parsed JSON response data

        Raises:
            UniFiAPIError: For API errors
        """
        url = f"{self._base_url}{endpoint}"

        method = method.upper()
        cacheable = method == "GET"
        invalidating = not cacheable or _no_cache
        cache_key: tuple[Any, ...] | None = None
        request_generation: int | None = None
        fresh_finalized = False
        if cacheable:
            device_identity = (
                self.device.name
                if self.device is not None
                else self.ctx.settings.default_device_name
            )
            cache_key = (
                self._base_url,
                device_identity,
                endpoint,
                self._normalize_cache_value(kwargs),
            )
            if not _no_cache and cache_key in self.ctx.cache:
                logger.debug("Cache hit for GET %s", endpoint)
                return self.ctx.cache[cache_key]

        if invalidating:
            self.ctx.cache_generation += 1
            self.ctx.cache.clear()
        request_generation = self.ctx.cache_generation

        try:
            response = await self._make_request(method, url, **kwargs)

            # Handle 401 - try to refresh session once (session-auth mode only)
            if response.status_code == 401 and isinstance(self.ctx.auth, UniFiLocalAuth):
                logger.info("Session expired, refreshing authentication")
                try:
                    await self.ctx.auth.refresh_session()
                    response = await self._make_request(method, url, **kwargs)
                except UniFiAuthError:
                    raise UniFiAuthError("Session expired and refresh failed") from None

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                raise UniFiRateLimitError(
                    f"Rate limited, retry after {retry_after}s",
                    retry_after=retry_after,
                )

            # Handle other errors
            if response.status_code >= 400:
                await self._handle_error_response(response)

            parsed = self._parse_response(response)
        finally:
            if not cacheable:
                self.ctx.cache_generation += 1
                self.ctx.cache.clear()
            elif _no_cache and self.ctx.cache_generation == request_generation:
                self.ctx.cache_generation += 1
                self.ctx.cache.clear()
                fresh_finalized = True

        if (
            cacheable
            and cache_key is not None
            and (
                (_no_cache and fresh_finalized)
                or (not _no_cache and self.ctx.cache_generation == request_generation)
            )
        ):
            self.ctx.cache[cache_key] = parsed
        return parsed

    async def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Make a GET request."""
        return await self.request("GET", endpoint, **kwargs)

    async def post(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Make a POST request."""
        return await self.request("POST", endpoint, **kwargs)

    async def put(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Make a PUT request."""
        return await self.request("PUT", endpoint, **kwargs)

    async def delete(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Make a DELETE request."""
        return await self.request("DELETE", endpoint, **kwargs)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse API response.

        Traditional controller responses use format:
        {
            "meta": {"rc": "ok"},
            "data": [...]
        }

        Integration/Cloud APIs return data directly or in a simpler format.

        Args:
            response: HTTP response

        Returns:
            Parsed response data
        """
        try:
            data = response.json()
        except Exception as e:
            # 204 No Content / empty bodies (common on DELETE) are success
            if not response.content:
                return {"meta": {"rc": "ok"}}
            raise UniFiAPIError(f"Failed to parse response: {e}") from e

        # Cloud API returns data directly without meta wrapper
        if isinstance(data, dict) and data.get("error"):
            raise UniFiAPIError(str(data["error"]), response.status_code, data)

        # Check for API-level errors (local controller format)
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        if meta.get("rc") == "error":
            msg = meta.get("msg", "Unknown API error")
            raise UniFiAPIError(msg, response.status_code, data)

        return data

    async def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses.

        Args:
            response: HTTP response with error status

        Raises:
            UniFiAuthError: For 401/403
            UniFiAPIError: For other errors
        """
        try:
            data = response.json()
            error_msg = data.get("meta", {}).get("msg", "")
            if not error_msg:
                error_msg = data.get("error", data.get("message", "Unknown error"))
        except Exception:
            error_msg = response.text[:500] or "Unknown error"

        if response.status_code == 401:
            raise UniFiAuthError(f"Authentication required: {error_msg}")
        if response.status_code == 403:
            raise UniFiAuthError(f"Access forbidden - check API key permissions: {error_msg}")

        raise UniFiAPIError(error_msg, response.status_code)


@asynccontextmanager
async def create_app_lifespan(
    server: MCPServer,
) -> AsyncIterator[AppContext]:
    """Create and manage application lifecycle.

    Initializes HTTP client, authentication, and cache on startup.
    Cleans up resources on shutdown.

    Authentication strategy:
    - Devices configured via UNIFI_DEVICES or legacy URL+key vars use
      per-device Integration API keys (no global login needed).
    - Legacy ``mode=local`` uses session-based username/password auth.

    Args:
        server: MCPServer instance

    Yields:
        AppContext with initialized resources
    """
    logger.info("Initializing UniFi MCP Server")

    # Create HTTP client with connection pooling
    client = httpx.AsyncClient(
        timeout=settings.request_timeout,
        limits=httpx.Limits(
            max_keepalive_connections=5,
            max_connections=settings.max_connections,
        ),
        verify=settings.verify_ssl,
    )

    # Initialize cache
    cache: TTLCache = TTLCache(maxsize=100, ttl=settings.cache_ttl)

    # Determine authentication mode
    auth: UniFiLocalAuth | UniFiCloudAuth | None = None
    runtime: RuntimeStore | None = None
    runtime_services: Any | None = None
    runtime_webhook_client: httpx.AsyncClient | None = None
    scheduler_task: asyncio.Task[None] | None = None
    primary_exception: BaseException | None = None

    try:
        if settings.runtime_enabled:
            runtime = RuntimeStore(settings.runtime_database_path)
            await runtime.open()

        if settings.mode == "local":
            # Explicit legacy session mode
            if not settings.controller_url:
                raise UniFiConfigError("UNIFI_CONTROLLER_URL is required for mode=local")
            auth = UniFiLocalAuth(client, settings)
            logger.info(f"Using local session authentication for {settings.controller_url}")
        elif settings.devices:
            # Device configs carry their own API keys (Integration API).
            names = settings.get_device_names()
            logger.info(f"Using Integration API keys for devices: {names}")
        elif settings.mode == "cloud":
            if not settings.cloud_api_key:
                raise UniFiConfigError("UNIFI_CLOUD_API_KEY is required for mode=cloud")
            auth = UniFiCloudAuth(settings.cloud_api_key)
            logger.info("Using cloud authentication (api.ui.com)")
        else:
            raise UniFiConfigError(
                "No UniFi devices configured. Set UNIFI_DEVICES (JSON array) "
                "or UNIFI_CONTROLLER_URL + UNIFI_CLOUD_API_KEY."
            )

        ctx = AppContext(
            client=client,
            settings=settings,
            cache=cache,
            auth=auth,
            runtime=runtime,
        )

        # Authenticate on startup (local session mode only)
        if isinstance(auth, UniFiLocalAuth):
            await auth.login()
            logger.info("Successfully authenticated with UniFi controller")

        if runtime is not None:
            from unifi_mcp.runtime.services import build_runtime_services

            runtime_webhook_client = httpx.AsyncClient(
                timeout=settings.webhook_timeout_seconds,
                follow_redirects=False,
            )
            runtime_services = await build_runtime_services(ctx, runtime_webhook_client)
            ctx.runtime_services = runtime_services
            if settings.automation_enabled:
                scheduler_task = asyncio.create_task(
                    runtime_services.scheduler.serve(
                        tick_seconds=settings.automation_tick_seconds,
                        max_jobs=settings.automation_max_concurrent_jobs,
                    ),
                    name="unifi-runtime-scheduler",
                )

        yield ctx

    except BaseException as exc:
        primary_exception = exc
        raise
    finally:
        logger.info("Shutting down UniFi MCP Server")

        cleanup_steps = []
        if scheduler_task is not None:

            async def stop_scheduler() -> None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task

            cleanup_steps.append(("automation scheduler", stop_scheduler))
        if runtime_services is not None:
            cleanup_steps.append(("runtime services", runtime_services.close))
        elif runtime_webhook_client is not None:
            cleanup_steps.append(("runtime webhook client", runtime_webhook_client.aclose))
        if runtime is not None:
            cleanup_steps.append(("runtime store", runtime.close))
        if isinstance(auth, UniFiLocalAuth):
            cleanup_steps.append(("authentication session", auth.logout))
        cleanup_steps.append(("HTTP client", client.aclose))

        first_cleanup_error: BaseException | None = None
        for resource, cleanup in cleanup_steps:
            try:
                await cleanup()
            except BaseException as cleanup_error:
                if primary_exception is not None:
                    logger.error(
                        "Failed to clean up %s while handling %s",
                        resource,
                        type(primary_exception).__name__,
                        exc_info=(
                            type(cleanup_error),
                            cleanup_error,
                            cleanup_error.__traceback__,
                        ),
                    )
                elif first_cleanup_error is None:
                    first_cleanup_error = cleanup_error
                else:
                    logger.error(
                        "Additional failure cleaning up %s",
                        resource,
                        exc_info=(
                            type(cleanup_error),
                            cleanup_error,
                            cleanup_error.__traceback__,
                        ),
                    )

        if primary_exception is None and first_cleanup_error is not None:
            raise first_cleanup_error
        logger.info("Cleanup complete")
