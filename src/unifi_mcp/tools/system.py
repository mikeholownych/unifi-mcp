"""Redaction-safe server health metadata."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from unifi_mcp.clients.base import AppContext
from unifi_mcp.version import get_version


class _StrictHealthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_boolean_types(cls, data: object) -> object:
        if isinstance(data, dict):
            for field in ("enabled", "connected"):
                if field in data and type(data[field]) is not bool:
                    raise ValueError(f"{field} must be a boolean")
        return data


class DisabledPersistenceHealth(_StrictHealthModel):
    """Health shape when runtime persistence is disabled."""

    enabled: Literal[False]
    connected: Literal[False]


class EnabledPersistenceHealth(_StrictHealthModel):
    """Health shape for an enabled runtime store."""

    enabled: Literal[True]
    connected: bool
    schema_version: int
    journal_mode: str


class ServiceHealth(_StrictHealthModel):
    """Configured device counts by UniFi service."""

    network: int
    protect: int


PersistenceHealth = Annotated[
    DisabledPersistenceHealth | EnabledPersistenceHealth,
    Field(discriminator="enabled"),
]


class ServerHealth(_StrictHealthModel):
    """Redaction-safe UniFi MCP server health response."""

    status: Literal["ok"]
    version: str
    transport: Literal["stdio"]
    configured_devices: int
    services: ServiceHealth
    persistence: PersistenceHealth


async def build_server_health(ctx: AppContext) -> ServerHealth:
    """Build server health without exposing configuration or credentials."""
    devices = ctx.settings.devices
    if ctx.runtime is None:
        persistence: DisabledPersistenceHealth | EnabledPersistenceHealth = (
            DisabledPersistenceHealth(enabled=False, connected=False)
        )
    else:
        runtime_health = await ctx.runtime.health()
        persistence = EnabledPersistenceHealth(
            enabled=True,
            connected=runtime_health["connected"],
            schema_version=runtime_health["schema_version"],
            journal_mode=runtime_health["journal_mode"],
        )

    return ServerHealth(
        status="ok",
        version=get_version(),
        transport="stdio",
        configured_devices=len(devices),
        services=ServiceHealth(
            network=sum(device.has_network for device in devices),
            protect=sum(device.has_protect for device in devices),
        ),
        persistence=persistence,
    )
