"""Per-tool HTTP OIDC scope authorization tests."""

from types import SimpleNamespace

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.shared.exceptions import MCPError
from mcp.types import Tool, ToolAnnotations

from unifi_mcp.auth.authorization import ScopeAuthorizer, ScopeMiddleware


def access_token(*scopes):
    return AccessToken(token="redacted", client_id="client", scopes=list(scopes))


async def call_tool(middleware, name):
    context = SimpleNamespace(method="tools/call", params={"name": name})
    called = False

    async def next_handler(_context):
        nonlocal called
        called = True
        return {"ok": True}

    result = await middleware(context, next_handler)
    return result, called


async def test_read_tool_requires_read_scope():
    middleware = ScopeMiddleware(
        ScopeAuthorizer("read", "write", "admin"),
        token_getter=lambda: access_token("read"),
    )

    result, called = await call_tool(middleware, "list_clients")

    assert result == {"ok": True}
    assert called is True


async def test_write_tool_requires_read_and_write_scopes():
    middleware = ScopeMiddleware(
        ScopeAuthorizer("read", "write", "admin"),
        token_getter=lambda: access_token("read"),
    )

    with pytest.raises(MCPError, match="insufficient scope"):
        await call_tool(middleware, "block_client")


async def test_schedule_mutation_requires_admin_in_addition_to_write():
    middleware = ScopeMiddleware(
        ScopeAuthorizer("read", "write", "admin"),
        token_getter=lambda: access_token("read", "write"),
    )

    with pytest.raises(MCPError, match="insufficient scope"):
        await call_tool(middleware, "create_interval_schedule")


async def test_plugin_status_requires_read_and_admin_but_not_write():
    middleware = ScopeMiddleware(
        ScopeAuthorizer("read", "write", "admin"),
        token_getter=lambda: access_token("read", "admin"),
    )

    result, called = await call_tool(middleware, "get_plugin_status")

    assert result == {"ok": True}
    assert called is True


async def test_plugin_tool_policy_is_merged_after_registration():
    authorizer = ScopeAuthorizer("read", "write", "admin")
    authorizer.add_plugin_tool("plugin_mutation", "write")
    middleware = ScopeMiddleware(
        authorizer,
        token_getter=lambda: access_token("read"),
    )

    with pytest.raises(MCPError, match="insufficient scope"):
        await call_tool(middleware, "plugin_mutation")


async def test_non_tool_requests_pass_through_without_scope_lookup():
    context = SimpleNamespace(method="initialize", params={})
    middleware = ScopeMiddleware(
        ScopeAuthorizer("read", "write", "admin"), token_getter=lambda: None
    )

    result = await middleware(context, lambda _context: async_result({"initialized": True}))

    assert result == {"initialized": True}


def test_policy_audit_rejects_unclassified_non_read_tool():
    authorizer = ScopeAuthorizer("read", "write", "admin")
    tool = Tool(name="future_mutation", inputSchema={"type": "object"})

    with pytest.raises(ValueError, match="future_mutation"):
        authorizer.audit_tools([tool])


def test_policy_audit_accepts_explicit_read_tool():
    authorizer = ScopeAuthorizer("read", "write", "admin")
    tool = Tool(
        name="future_read",
        inputSchema={"type": "object"},
        annotations=ToolAnnotations(read_only_hint=True),
    )

    authorizer.audit_tools([tool])


def test_camera_export_requires_write_scope():
    authorizer = ScopeAuthorizer("read", "write", "admin")

    assert authorizer.required_scopes("export_camera_clip") == {"read", "write"}


async def async_result(value):
    return value
