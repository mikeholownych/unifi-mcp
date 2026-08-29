"""Authentication modules for UniFi APIs and optional remote MCP transport."""

from unifi_mcp.auth.local import UniFiCloudAuth, UniFiLocalAuth

__all__ = ["UniFiLocalAuth", "UniFiCloudAuth"]
