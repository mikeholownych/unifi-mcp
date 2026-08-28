"""Strict allowlist for background job handlers."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class JobDefinition:
    """One callable background operation and its argument contract."""

    name: str
    arguments_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[dict[str, Any]]]
    retryable: bool = False


class JobRegistry:
    """Resolve only explicitly registered jobs."""

    def __init__(self, definitions: Iterable[JobDefinition]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        if not self._definitions:
            raise ValueError("at least one allowlisted job is required")

    def get(self, name: str) -> JobDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ValueError(f"{name!r} is not an allowlisted job") from exc

    def validate(self, name: str, arguments: dict[str, object]) -> BaseModel:
        definition = self.get(name)
        unknown = sorted(set(arguments) - set(definition.arguments_model.model_fields))
        if unknown:
            raise ValueError(f"unknown job arguments: {', '.join(unknown)}")
        return definition.arguments_model.model_validate(arguments)
