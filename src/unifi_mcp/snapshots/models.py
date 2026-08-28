"""Strict portable snapshot schema."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceScope(SnapshotModel):
    source: Literal["network", "protect"]
    device_name: str = Field(min_length=1, max_length=128)
    site: str = Field(default="", max_length=128)
    mode: str = Field(min_length=1, max_length=64)
    status: Literal["complete", "partial", "unsupported", "failed"]


class SnapshotLimitation(SnapshotModel):
    source: Literal["network", "protect"]
    device_name: str = Field(min_length=1, max_length=128)
    site: str = Field(default="", max_length=128)
    code: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=500)


class DeviceSnapshot(SnapshotModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    service: Literal["network", "protect"]
    controller: str = Field(default="", max_length=128)
    site: str = Field(default="", max_length=128)
    kind: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=64)


class NetworkSnapshot(SnapshotModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    controller: str = Field(default="", max_length=128)
    site: str = Field(default="", max_length=128)
    purpose: str | None = Field(default=None, max_length=64)
    subnet: str | None = Field(default=None, max_length=128)
    vlan: int | None = Field(default=None, ge=1, le=4094)


class WlanSnapshot(SnapshotModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    controller: str = Field(default="", max_length=128)
    site: str = Field(default="", max_length=128)
    enabled: bool
    security: str | None = Field(default=None, max_length=64)
    hidden: bool = False


class FirewallSnapshot(SnapshotModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    controller: str = Field(default="", max_length=128)
    site: str = Field(default="", max_length=128)
    kind: Literal["rule", "policy"]
    action: str | None = Field(default=None, max_length=64)
    enabled: bool = True


class SnapshotContent(SnapshotModel):
    sources: list[SourceScope] = Field(default_factory=list, max_length=256)
    limitations: list[SnapshotLimitation] = Field(default_factory=list, max_length=1000)
    devices: list[DeviceSnapshot] = Field(default_factory=list, max_length=10_000)
    networks: list[NetworkSnapshot] = Field(default_factory=list, max_length=5000)
    wlans: list[WlanSnapshot] = Field(default_factory=list, max_length=5000)
    firewall: list[FirewallSnapshot] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def sort_and_require_unique_identities(self) -> "SnapshotContent":
        collections = (
            (self.sources, lambda item: (item.source, item.device_name, item.site)),
            (
                self.limitations,
                lambda item: (item.source, item.device_name, item.site, item.code),
            ),
            (self.devices, lambda item: (item.service, item.controller, item.site, item.id)),
            (self.networks, lambda item: (item.controller, item.site, item.id)),
            (self.wlans, lambda item: (item.controller, item.site, item.id)),
            (
                self.firewall,
                lambda item: (item.controller, item.site, item.kind, item.id),
            ),
        )
        for collection, identity in collections:
            collection.sort(key=identity)
            identities = [identity(item) for item in collection]
            if len(identities) != len(set(identities)):
                raise ValueError("snapshot collections must not contain duplicate identities")
        return self


class SnapshotDocument(SnapshotModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    redaction_status: Literal["secrets_excluded"] = "secrets_excluded"
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: SnapshotContent

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value.astimezone(UTC)
