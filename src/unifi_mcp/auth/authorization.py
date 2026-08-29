"""OIDC scope policy for remote MCP tool calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.shared.exceptions import MCPError

_WRITE_TOOLS = {
    "apply_client_qos_policy",
    "archive_all_alarms",
    "assign_client_group",
    "block_client",
    "capture_observations_now",
    "create_client_group",
    "create_firewall_policy",
    "create_interval_schedule",
    "create_network",
    "create_port_forward",
    "create_webhook_destination",
    "create_wlan",
    "delete_client_group",
    "delete_firewall_policy",
    "delete_network",
    "delete_port_forward",
    "delete_schedule",
    "delete_webhook_destination",
    "delete_wlan",
    "export_network_report",
    "export_portable_snapshot",
    "export_camera_clip",
    "forget_client",
    "kick_client",
    "locate_device",
    "plan_client_qos_policy",
    "poll_events_now",
    "provision_device",
    "reserve_client_ip",
    "restart_device",
    "run_schedule_now",
    "run_speed_test",
    "set_client_tags",
    "set_device_port",
    "set_firewall_policy_enabled",
    "set_schedule_enabled",
    "set_webhook_destination_enabled",
    "test_webhook_destination",
    "unblock_client",
    "update_network",
    "update_wlan",
    "upgrade_device",
}
_ADMIN_MUTATIONS = {
    "capture_observations_now",
    "create_interval_schedule",
    "create_webhook_destination",
    "delete_schedule",
    "delete_webhook_destination",
    "poll_events_now",
    "run_schedule_now",
    "set_schedule_enabled",
    "set_webhook_destination_enabled",
    "test_webhook_destination",
}
_ADMIN_READS = {"get_plugin_status"}


class ScopeAuthorizer:
    def __init__(self, read_scope: str, write_scope: str, admin_scope: str) -> None:
        self._read_scope = read_scope
        self._write_scope = write_scope
        self._admin_scope = admin_scope
        self._plugin_scopes: dict[str, str] = {}

    def add_plugin_tool(self, name: str, scope: str) -> None:
        if scope not in {"read", "write", "admin"}:
            raise ValueError("plugin scope must be read, write, or admin")
        self._plugin_scopes[name] = scope

    def required_scopes(self, name: str) -> set[str]:
        required = {self._read_scope}
        plugin_scope = self._plugin_scopes.get(name)
        if plugin_scope in {"write", "admin"} or name in _WRITE_TOOLS:
            required.add(self._write_scope)
        if plugin_scope == "admin" or name in _ADMIN_MUTATIONS or name in _ADMIN_READS:
            required.add(self._admin_scope)
        return required

    def audit_tools(self, tools: list[Any]) -> None:
        unclassified = []
        for tool in tools:
            if tool.name in self._plugin_scopes:
                continue
            annotations = tool.annotations
            if (
                not (annotations and annotations.read_only_hint is True)
                and tool.name not in _WRITE_TOOLS
            ):
                unclassified.append(tool.name)
        if unclassified:
            raise ValueError(
                "HTTP scope policy is missing classifications for: "
                + ", ".join(sorted(unclassified))
            )


class ScopeMiddleware:
    def __init__(
        self,
        authorizer: ScopeAuthorizer,
        *,
        token_getter: Callable[[], AccessToken | None] = get_access_token,
    ) -> None:
        self._authorizer = authorizer
        self._token_getter = token_getter

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = ctx.params or {}
        name = params.get("name") if hasattr(params, "get") else None
        if not isinstance(name, str):
            return await call_next(ctx)
        token = self._token_getter()
        required = self._authorizer.required_scopes(name)
        if token is None or not required <= set(token.scopes):
            raise MCPError(-32001, "authentication failed: insufficient scope")
        return await call_next(ctx)
