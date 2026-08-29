"""Optional Streamable HTTP transport construction and startup tests."""

from types import SimpleNamespace

import httpx
from mcp.server.mcpserver import MCPServer

from unifi_mcp.config import UniFiSettings
from unifi_mcp.server import _build_server_security, main


def http_settings(tmp_path):
    return UniFiSettings(
        _env_file=None,
        data_dir=tmp_path,
        transport="streamable-http",
        oidc_issuer="https://identity.example.com",
        oidc_audience="unifi-mcp",
        http_public_url="https://mcp.example.com/mcp",
    )


def test_stdio_builds_without_authentication_middleware(tmp_path):
    options, authorizer = _build_server_security(UniFiSettings(_env_file=None, data_dir=tmp_path))

    assert options == {}
    assert authorizer is None


async def test_http_app_rejects_missing_bearer_token(tmp_path):
    configured = http_settings(tmp_path)
    options, authorizer = _build_server_security(configured)
    server = MCPServer(name="test", **options)
    app = server.streamable_http_app(host="127.0.0.1")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.com"
    ) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )

    assert authorizer is not None
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_main_selects_native_streamable_http_with_configured_binding(monkeypatch):
    calls = []
    configured = SimpleNamespace(
        transport="streamable-http",
        http_host="127.0.0.1",
        http_port=8123,
        http_path="/mcp",
        devices=[],
        get_device_names=lambda: [],
    )
    monkeypatch.setattr("unifi_mcp.server.settings", configured)
    monkeypatch.setattr(
        "unifi_mcp.server.mcp.run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    main()

    assert calls == [
        (
            ("streamable-http",),
            {"host": "127.0.0.1", "port": 8123, "streamable_http_path": "/mcp"},
        )
    ]
