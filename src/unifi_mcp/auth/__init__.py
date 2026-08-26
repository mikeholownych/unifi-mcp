"""Authentication modules for UniFi APIs."""

from unifi_mcp.auth.local import UniFiCloudAuth, UniFiLocalAuth

__all__ = ["UniFiLocalAuth", "UniFiCloudAuth"]
