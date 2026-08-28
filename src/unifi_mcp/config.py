"""Configuration settings for UniFi MCP Server."""

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Look for .env in the current directory first, then in the project root.
# This allows the server to be launched from any working directory.
_ENV_FILES = (
    ".env",
    str(Path(__file__).resolve().parents[2] / ".env"),
)


def _default_data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        try:
            xdg_path = Path(xdg_data_home).expanduser()
        except RuntimeError:
            xdg_path = Path(xdg_data_home)
        if xdg_path.is_absolute():
            return xdg_path / "unifi-mcp"
    return Path.home() / ".local" / "share" / "unifi-mcp"


def _validate_absolute_path(value: object, field_name: str) -> Path:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name} must be a non-empty absolute path")

    try:
        path = Path(value).expanduser()  # type: ignore[arg-type]
    except (RuntimeError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a valid absolute path") from exc
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path; got {value!r}")
    return path


class UniFiDevice(BaseModel):
    """Configuration for a single UniFi device."""

    name: str = Field(description="Friendly name for the device")
    url: str = Field(description="Base URL of the device (e.g., https://10.1.3.1)")
    api_key: str = Field(description="API key for the device")
    services: list[Literal["network", "protect"]] = Field(
        default=["network"],
        description="Services available on this device",
    )
    site: str = Field(
        default="default",
        description="Site name for network operations",
    )
    verify_ssl: bool = Field(
        default=False,
        description="Verify SSL certificates",
    )
    # Optional credentials for full Protect API access (events, recordings)
    username: str | None = Field(
        default=None,
        description="Username for session auth (required for Protect events)",
    )
    password: str | None = Field(
        default=None,
        description="Password for session auth (required for Protect events)",
    )

    @property
    def network_api_base(self) -> str:
        """Get the Network Integration API base URL."""
        return f"{self.url.rstrip('/')}/proxy/network/integration"

    @property
    def protect_api_base(self) -> str:
        """Get the Protect Integration API base URL."""
        return f"{self.url.rstrip('/')}/proxy/protect/integration/v1"

    @property
    def protect_internal_api_base(self) -> str:
        """Get the internal Protect API base URL (for events/recordings)."""
        return f"{self.url.rstrip('/')}/proxy/protect/api"

    @property
    def has_network(self) -> bool:
        """Check if device has Network service."""
        return "network" in self.services

    @property
    def has_protect(self) -> bool:
        """Check if device has Protect service."""
        return "protect" in self.services

    @property
    def has_protect_credentials(self) -> bool:
        """Check if device has credentials for full Protect API access."""
        return bool(self.username and self.password)


class UniFiSettings(BaseSettings):
    """UniFi MCP Server configuration.

    Supports multiple UniFi devices with different services.

    Configuration can be done via:
    1. UNIFI_DEVICES JSON array (recommended for multiple devices)
    2. Legacy single-device env vars (UNIFI_CONTROLLER_URL, UNIFI_CLOUD_API_KEY, etc.)
    """

    model_config = SettingsConfigDict(
        env_prefix="UNIFI_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Multi-device configuration (JSON array)
    devices_json: str | None = Field(
        default=None,
        validation_alias="UNIFI_DEVICES",
        description="JSON array of device configurations",
    )

    # Legacy single-device settings (for backwards compatibility)
    mode: Literal["local", "local_api_key", "cloud"] = Field(
        default="local_api_key",
        description="Connection mode for legacy single-device config",
    )
    controller_url: str | None = Field(
        default=None,
        description="URL of the UniFi controller",
    )
    cloud_api_key: str | None = Field(
        default=None,
        description="API key for the device",
    )
    username: str | None = Field(default=None)
    password: str | None = Field(default=None)
    site: str = Field(default="default")
    verify_ssl: bool = Field(default=False)
    is_udm: bool = Field(default=True)

    # Performance settings
    request_timeout: float = Field(default=30.0)
    max_connections: int = Field(default=10)
    cache_ttl: int = Field(default=30)
    mutation_verify_attempts: int = Field(default=5, ge=1, le=10)
    mutation_verify_initial_delay: float = Field(default=0.5, ge=0, le=60)
    mutation_verify_max_delay: float = Field(default=2.0, ge=0, le=60)

    # Optional runtime persistence
    runtime_enabled: bool = Field(default=False)
    data_dir: Path = Field(default_factory=_default_data_dir)
    runtime_database: Path | None = Field(default=None)

    # Default device name for legacy config
    default_device_name: str = Field(
        default="default",
        description="Name for the default device when using legacy config",
    )

    _devices: list[UniFiDevice] | None = None

    @property
    def runtime_database_path(self) -> Path:
        """Return the configured runtime database path."""
        return self.runtime_database or self.data_dir / "runtime.db"

    @field_validator("data_dir", mode="before")
    @classmethod
    def validate_data_dir(cls, value: object) -> Path:
        """Expand and validate the runtime data directory."""
        return _validate_absolute_path(value, "data_dir")

    @field_validator("runtime_database", mode="before")
    @classmethod
    def validate_runtime_database(cls, value: object) -> Path | None:
        """Expand and validate an optional runtime database override."""
        if value is None:
            return None
        return _validate_absolute_path(value, "runtime_database")

    @field_validator("devices_json", mode="before")
    @classmethod
    def parse_devices_json(cls, v):
        """Parse devices JSON if provided as string."""
        if v is None:
            return None
        if isinstance(v, str):
            # Strip leading/trailing quotes that might be included from .env
            v = v.strip()
            if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
                v = v[1:-1]
            return v
        if isinstance(v, list):
            return json.dumps(v)
        return v

    @model_validator(mode="after")
    def validate_mutation_verify_delays(self) -> "UniFiSettings":
        """Ensure exponential verification delays can only increase."""
        if self.mutation_verify_max_delay < self.mutation_verify_initial_delay:
            raise ValueError(
                "mutation_verify_max_delay must be greater than or equal to "
                "mutation_verify_initial_delay"
            )
        return self

    @property
    def devices(self) -> list[UniFiDevice]:
        """Get list of configured devices."""
        if self._devices is not None:
            return self._devices

        devices = []

        # Parse multi-device JSON config
        if self.devices_json:
            try:
                devices_data = json.loads(self.devices_json)
                for d in devices_data:
                    devices.append(UniFiDevice(**d))
                logger.info(f"Loaded {len(devices)} devices from UNIFI_DEVICES config")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse UNIFI_DEVICES: {e}")

        # Fall back to legacy single-device config
        if not devices and self.controller_url and self.cloud_api_key:
            devices.append(
                UniFiDevice(
                    name=self.default_device_name,
                    url=self.controller_url,
                    api_key=self.cloud_api_key,
                    services=["network"],  # Legacy config only supported network
                    site=self.site,
                    verify_ssl=self.verify_ssl,
                )
            )
            logger.info(f"Using legacy single-device config: {self.controller_url}")

        self._devices = devices
        return devices

    def get_device(self, name: str | None = None) -> UniFiDevice | None:
        """Get a device by name.

        Args:
            name: Device name. If None, returns the first device.

        Returns:
            UniFiDevice or None if not found.
        """
        if not self.devices:
            return None

        if name is None:
            return self.devices[0]

        for device in self.devices:
            if device.name.lower() == name.lower():
                return device

        return None

    def get_network_devices(self) -> list[UniFiDevice]:
        """Get all devices with Network service."""
        return [d for d in self.devices if d.has_network]

    def get_protect_devices(self) -> list[UniFiDevice]:
        """Get all devices with Protect service."""
        return [d for d in self.devices if d.has_protect]

    def get_device_names(self) -> list[str]:
        """Get list of all device names."""
        return [d.name for d in self.devices]

    # Legacy compatibility properties
    @property
    def api_base_url(self) -> str:
        """Get the base URL for API requests (legacy compatibility)."""
        if self.mode == "cloud":
            return "https://api.ui.com"

        device = self.get_device()
        if device and self.mode != "local":
            return device.network_api_base

        if not self.controller_url:
            raise ValueError("No device configured")

        base = self.controller_url.rstrip("/")
        if self.is_udm:
            return f"{base}/proxy/network"
        return base

    @property
    def uses_api_key(self) -> bool:
        """Check if using API key authentication."""
        if self.devices:
            return True
        return self.mode in ("cloud", "local_api_key") and bool(self.cloud_api_key)

    @property
    def auth_url(self) -> str:
        """Get the login URL for local session authentication."""
        if not self.controller_url:
            raise ValueError("Controller URL is required for local authentication")

        base = self.controller_url.rstrip("/")
        if self.is_udm:
            return f"{base}/api/auth/login"
        return f"{base}/api/login"

    @property
    def logout_url(self) -> str:
        """Get the logout URL for local session authentication."""
        if not self.controller_url:
            raise ValueError("Controller URL is required for local authentication")

        base = self.controller_url.rstrip("/")
        if self.is_udm:
            return f"{base}/api/auth/logout"
        return f"{base}/api/logout"


# Global settings instance
settings = UniFiSettings()
