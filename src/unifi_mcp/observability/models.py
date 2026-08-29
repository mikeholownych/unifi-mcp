"""Strict low-cardinality historical observation models."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SiteHealthMetrics(ObservationModel):
    subsystem_total: int = Field(ge=0)
    healthy: int = Field(ge=0)
    issues: int = Field(ge=0)
    wan_up: bool | None = None


class DeviceCountMetrics(ObservationModel):
    total: int = Field(ge=0)
    online: int = Field(ge=0)
    offline: int = Field(ge=0)


class ClientCountMetrics(ObservationModel):
    total: int = Field(ge=0)
    wired: int = Field(ge=0)
    wireless: int = Field(ge=0)


class TrafficMetrics(ObservationModel):
    rx_bytes: float = Field(ge=0)
    tx_bytes: float = Field(ge=0)


class ProtectHealthMetrics(ObservationModel):
    total: int = Field(ge=0)
    online: int = Field(ge=0)
    offline: int = Field(ge=0)


Metrics = (
    SiteHealthMetrics
    | DeviceCountMetrics
    | ClientCountMetrics
    | TrafficMetrics
    | ProtectHealthMetrics
)


class Observation(ObservationModel):
    source: Literal["network", "protect"]
    controller: str = Field(min_length=1, max_length=128)
    site: str = Field(default="", max_length=128)
    kind: Literal["site_health", "device_counts", "client_counts", "traffic", "protect_health"]
    status: Literal["ok", "issues", "unavailable"]
    observed_at: datetime
    metrics: Metrics

    @field_validator("observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_metrics_for_kind(self) -> "Observation":
        expected = {
            "site_health": SiteHealthMetrics,
            "device_counts": DeviceCountMetrics,
            "client_counts": ClientCountMetrics,
            "traffic": TrafficMetrics,
            "protect_health": ProtectHealthMetrics,
        }[self.kind]
        if not isinstance(self.metrics, expected):
            raise ValueError(f"{self.kind} requires {expected.__name__}")
        return self


class TrendBucket(ObservationModel):
    start: datetime
    end: datetime
    present: bool
    value: float | None
    sample_count: int = Field(ge=0)
