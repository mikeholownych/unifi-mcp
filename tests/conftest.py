"""Shared test fixtures for UniFi MCP tests."""

import httpx
import pytest

from unifi_mcp.clients.base import AppContext
from unifi_mcp.config import UniFiSettings


@pytest.fixture
def mock_ctx():
    """Create a minimal AppContext with a single test device."""
    settings = UniFiSettings(
        _env_file=None,
        devices_json='[{"name":"test-gw","url":"https://10.0.0.1","api_key":"test-key","services":["network"],"site":"default"}]',
    )
    return AppContext(
        client=httpx.AsyncClient(verify=False),
        settings=settings,
        cache={},
        auth=None,
    )
