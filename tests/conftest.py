"""Shared test fixtures for UniFi MCP tests."""

import os

import httpx
import pytest

for _name in ("UNIFI_RUNTIME_DATABASE", "UNIFI_DATA_DIR", "UNIFI_RUNTIME_ENABLED"):
    os.environ.pop(_name, None)

from unifi_mcp.clients.base import AppContext  # noqa: E402
from unifi_mcp.config import UniFiSettings  # noqa: E402


@pytest.fixture
def mock_ctx():
    """Create a minimal AppContext with a single test device."""
    settings = UniFiSettings(
        _env_file=None,
        devices_json='[{"name":"test-gw","url":"https://10.0.0.1","api_key":"test-key","services":["network"],"site":"default"}]',
        mutation_verify_initial_delay=0,
        mutation_verify_max_delay=0,
    )
    return AppContext(
        client=httpx.AsyncClient(verify=False),
        settings=settings,
        cache={},
        auth=None,
    )
