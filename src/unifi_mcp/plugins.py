"""Allowlisted trusted-code plugin discovery and registration."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from inspect import iscoroutinefunction, signature
from typing import Any, Literal

from mcp.server.mcpserver.tools.base import Tool as SDKTool
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from unifi_mcp.runtime.jobs import JobDefinition

PLUGIN_API_VERSION = 1
PLUGIN_ENTRY_POINT_GROUP = "unifi_mcp.plugins"
PluginScope = Literal["read", "write", "admin"]
_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CORE_JOB_NAMES = {
    "capture_observations",
    "poll_events",
    "prune_runtime_data",
    "retry_webhook_deliveries",
}


class PluginError(RuntimeError):
    """A redacted plugin loading or registration failure."""


@dataclass(frozen=True)
class PluginTool:
    name: str
    function: Any
    scope: PluginScope
    description: str | None = None
    annotations: ToolAnnotations | None = None


@dataclass
class PluginRegistry:
    tools: dict[str, PluginTool] = field(default_factory=dict)
    collectors: dict[str, Any] = field(default_factory=dict)
    jobs: dict[str, Any] = field(default_factory=dict)
    notification_sinks: dict[str, Any] = field(default_factory=dict)
    report_renderers: dict[str, Any] = field(default_factory=dict)

    def register_tool(
        self,
        name: str,
        function: Any,
        *,
        scope: PluginScope,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
    ) -> None:
        self._validate_name(name)
        if scope not in {"read", "write", "admin"}:
            raise PluginError("plugin tool scope must be read, write, or admin")
        if name in self.tools:
            raise PluginError("duplicate plugin tool name")
        if not callable(function):
            raise PluginError("plugin tool must be callable")
        SDKTool.from_function(
            function,
            name=name,
            description=description,
            annotations=annotations,
        )
        self.tools[name] = PluginTool(name, function, scope, description, annotations)

    def register_collector(self, name: str, extension: Any) -> None:
        if not all(hasattr(extension, field) for field in ("source", "controller", "site")):
            raise PluginError("plugin collector must provide source, controller, and site")
        if not iscoroutinefunction(getattr(extension, "collect", None)):
            raise PluginError("plugin collector must provide async collect()")
        if len(signature(extension.collect).parameters) != 1:
            raise PluginError("plugin collector collect() must accept observed_at")
        self._register_named(self.collectors, name, extension)

    def register_job(self, name: str, extension: Any) -> None:
        if name in _CORE_JOB_NAMES:
            raise PluginError("plugin job name conflicts with a core job")
        if not isinstance(extension, JobDefinition):
            raise PluginError("plugin job must use the versioned job definition interface")
        if extension.name != name:
            raise PluginError("plugin job registration name must match its definition")
        if not isinstance(extension.arguments_model, type) or not issubclass(
            extension.arguments_model, BaseModel
        ):
            raise PluginError("plugin job arguments_model must inherit from BaseModel")
        if (
            not iscoroutinefunction(extension.handler)
            or len(signature(extension.handler).parameters) != 1
        ):
            raise PluginError("plugin job handler must be async and accept one arguments model")
        self._register_named(self.jobs, name, extension)

    def register_notification_sink(self, name: str, extension: Any) -> None:
        if not iscoroutinefunction(getattr(extension, "send", None)):
            raise PluginError("plugin notification sink must provide async send()")
        self._register_named(self.notification_sinks, name, extension)

    def register_report_renderer(self, name: str, extension: Any) -> None:
        if name in {"html", "csv"}:
            raise PluginError("plugin report renderer name conflicts with a core renderer")
        if not callable(extension):
            raise PluginError("plugin report renderer must be callable")
        self._register_named(self.report_renderers, name, extension)

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME.fullmatch(name):
            raise PluginError("plugin extension names must use lowercase stable identifiers")

    def _register_named(self, target: dict[str, Any], name: str, extension: Any) -> None:
        self._validate_name(name)
        if name in target:
            raise PluginError("duplicate plugin extension name")
        target[name] = extension

    def merged(self, staged: PluginRegistry, core_tool_names: set[str]) -> PluginRegistry:
        if (set(self.tools) | core_tool_names) & set(staged.tools):
            raise PluginError("plugin tool name conflicts with an existing tool")
        for current, incoming in (
            (self.collectors, staged.collectors),
            (self.jobs, staged.jobs),
            (self.notification_sinks, staged.notification_sinks),
            (self.report_renderers, staged.report_renderers),
        ):
            if set(current) & set(incoming):
                raise PluginError("plugin extension name conflicts with an existing extension")
        self.tools.update(staged.tools)
        self.collectors.update(staged.collectors)
        self.jobs.update(staged.jobs)
        self.notification_sinks.update(staged.notification_sinks)
        self.report_renderers.update(staged.report_renderers)
        return self


@dataclass(frozen=True)
class PluginStatus:
    name: str
    state: Literal["loaded", "skipped", "failed"]
    reason: str | None
    required: bool


@dataclass
class PluginManager:
    registry: PluginRegistry
    statuses: list[PluginStatus]

    @classmethod
    def load(
        cls,
        discovered: list[EntryPoint] | Any,
        *,
        allowlist: set[str],
        required: set[str],
        core_tool_names: set[str] | None = None,
    ) -> PluginManager:
        discovered = list(discovered)
        registry = PluginRegistry()
        statuses: list[PluginStatus] = []
        core_tool_names = core_tool_names or set()
        found: set[str] = set()
        counts = Counter(entry_point.name for entry_point in discovered)
        duplicates = {name for name, count in counts.items() if count > 1 and name in allowlist}
        required_duplicates = duplicates & required
        if required_duplicates:
            names = ", ".join(sorted(required_duplicates))
            raise PluginError(f"required plugin entry point is duplicated: {names}")
        statuses.extend(
            PluginStatus(name, "failed", "duplicate_entry_point", False)
            for name in sorted(duplicates)
        )
        for entry_point in discovered:
            name = entry_point.name
            found.add(name)
            is_required = name in required
            if name in duplicates:
                continue
            if name not in allowlist:
                statuses.append(PluginStatus(name, "skipped", "not_allowlisted", is_required))
                continue
            try:
                plugin = entry_point.load()
            except Exception:
                if is_required:
                    raise PluginError(f"required plugin {name!r} failed to load") from None
                statuses.append(PluginStatus(name, "failed", "load_failed", False))
                continue
            if getattr(plugin, "api_version", None) != PLUGIN_API_VERSION:
                if is_required:
                    raise PluginError(f"required plugin {name!r} has an incompatible API version")
                statuses.append(PluginStatus(name, "failed", "incompatible_api_version", False))
                continue
            staged = PluginRegistry()
            try:
                plugin.register(staged)
                registry.merged(staged, core_tool_names)
            except Exception:
                if is_required:
                    raise PluginError(f"required plugin {name!r} registration failed") from None
                statuses.append(PluginStatus(name, "failed", "registration_failed", False))
                continue
            statuses.append(PluginStatus(name, "loaded", None, is_required))

        missing = required - found
        if missing:
            names = ", ".join(sorted(missing))
            raise PluginError(f"required plugin is not installed: {names}")
        return cls(registry, statuses)

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "state": item.state,
                "reason": item.reason,
                "required": item.required,
            }
            for item in self.statuses
        ]


def discover_plugins() -> list[EntryPoint]:
    """Discover plugin metadata without importing plugin code."""
    return list(entry_points().select(group=PLUGIN_ENTRY_POINT_GROUP))


_active_registry = PluginRegistry()


def activate_plugins(manager: PluginManager) -> None:
    global _active_registry
    _active_registry = manager.registry


def active_plugin_registry() -> PluginRegistry:
    return _active_registry
