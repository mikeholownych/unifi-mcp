"""Strict normalized event models."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class NormalizedEvent(BaseModel):
    """Controller-independent event accepted by the runtime store."""

    source: str = Field(min_length=1, max_length=64)
    source_key: str = Field(min_length=1, max_length=256)
    device_name: str = Field(default="", max_length=128)
    site: str = Field(default="", max_length=128)
    category: str = Field(min_length=1, max_length=128)
    severity: Literal["info", "warning", "error", "critical"]
    occurred_at: datetime
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str = Field(min_length=1, max_length=1000)
    subject_type: str | None = Field(default=None, max_length=64)
    subject_id: str | None = Field(default=None, max_length=256)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at", "observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        """Persist unambiguous UTC timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must include a timezone")
        return value.astimezone(UTC)


class StoredEvent(NormalizedEvent):
    """Normalized event with runtime identity and insertion time."""

    id: str
    created_at: datetime
