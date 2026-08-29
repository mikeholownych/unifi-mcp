"""Trusted plugin discovery and registration tests."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from unifi_mcp.plugins import PluginError, PluginManager
from unifi_mcp.runtime.jobs import JobDefinition


@dataclass
class FakeEntryPoint:
    name: str
    plugin: object
    loaded: bool = False

    def load(self):
        self.loaded = True
        if isinstance(self.plugin, Exception):
            raise self.plugin
        return self.plugin


class ToolPlugin:
    api_version = 1

    def __init__(self, tool_name="plugin_tool", scope="read"):
        self.tool_name = tool_name
        self.scope = scope

    def register(self, registry):
        async def tool():
            return {"plugin": True}

        registry.register_tool(self.tool_name, tool, scope=self.scope)


def test_unallowlisted_entry_point_is_never_loaded():
    entry_point = FakeEntryPoint("untrusted", ToolPlugin())

    manager = PluginManager.load([entry_point], allowlist=set(), required=set())

    assert entry_point.loaded is False
    assert manager.status() == [
        {"name": "untrusted", "state": "skipped", "reason": "not_allowlisted", "required": False}
    ]


def test_allowlisted_plugin_registers_versioned_scoped_tool():
    entry_point = FakeEntryPoint("example", ToolPlugin())

    manager = PluginManager.load([entry_point], allowlist={"example"}, required=set())

    assert entry_point.loaded is True
    assert manager.registry.tools["plugin_tool"].scope == "read"
    assert manager.status()[0]["state"] == "loaded"


@pytest.mark.parametrize(
    ("plugin", "reason"),
    [
        (ToolPlugin(scope="owner"), "registration_failed"),
        (ToolPlugin(tool_name="core_tool"), "registration_failed"),
    ],
)
def test_invalid_or_duplicate_registration_is_isolated(plugin, reason):
    manager = PluginManager.load(
        [FakeEntryPoint("example", plugin)],
        allowlist={"example"},
        required=set(),
        core_tool_names={"core_tool"},
    )

    assert manager.registry.tools == {}
    assert manager.status()[0]["reason"] == reason


def test_incompatible_api_version_is_rejected():
    plugin = ToolPlugin()
    plugin.api_version = 2

    manager = PluginManager.load(
        [FakeEntryPoint("example", plugin)], allowlist={"example"}, required=set()
    )

    assert manager.status()[0]["reason"] == "incompatible_api_version"


def test_duplicate_allowlisted_entry_points_are_never_loaded():
    first = FakeEntryPoint("example", ToolPlugin("first_tool"))
    second = FakeEntryPoint("example", ToolPlugin("second_tool"))

    manager = PluginManager.load([first, second], allowlist={"example"}, required=set())

    assert first.loaded is False
    assert second.loaded is False
    assert manager.status()[0]["reason"] == "duplicate_entry_point"


def test_required_plugin_failure_aborts_startup():
    with pytest.raises(PluginError, match="required plugin"):
        PluginManager.load(
            [FakeEntryPoint("example", RuntimeError("secret details"))],
            allowlist={"example"},
            required={"example"},
        )


def test_missing_required_plugin_aborts_startup():
    with pytest.raises(PluginError, match="not installed"):
        PluginManager.load([], allowlist={"required"}, required={"required"})


def test_non_tool_extension_names_are_duplicate_safe():
    class ExtensionsPlugin:
        api_version = 1

        def register(self, registry):
            async def collect(_observed_at):
                return []

            async def handle(_arguments):
                return {}

            async def send():
                return None

            class Arguments(BaseModel):
                pass

            collector = SimpleNamespace(
                source="example", controller="test", site="default", collect=collect
            )
            job = JobDefinition("cleanup", Arguments, handle)
            sink = SimpleNamespace(send=send)
            registry.register_collector("health", collector)
            registry.register_job("cleanup", job)
            registry.register_notification_sink("chat", sink)
            registry.register_report_renderer("markdown", lambda _document: b"report")

    manager = PluginManager.load(
        [FakeEntryPoint("extensions", ExtensionsPlugin())],
        allowlist={"extensions"},
        required=set(),
    )

    assert list(manager.registry.collectors) == ["health"]
    assert list(manager.registry.jobs) == ["cleanup"]
    assert list(manager.registry.notification_sinks) == ["chat"]
    assert list(manager.registry.report_renderers) == ["markdown"]


def test_plugin_renderer_cannot_replace_core_format():
    class RendererPlugin:
        api_version = 1

        def register(self, registry):
            registry.register_report_renderer("html", lambda _document: b"replacement")

    manager = PluginManager.load(
        [FakeEntryPoint("renderer", RendererPlugin())],
        allowlist={"renderer"},
        required=set(),
    )

    assert manager.registry.report_renderers == {}
    assert manager.status()[0]["reason"] == "registration_failed"


def test_malformed_job_definition_is_rejected_during_registration():
    class JobPlugin:
        api_version = 1

        def register(self, registry):
            registry.register_job("bad", JobDefinition("bad", object, None))

    manager = PluginManager.load(
        [FakeEntryPoint("jobs", JobPlugin())], allowlist={"jobs"}, required=set()
    )

    assert manager.registry.jobs == {}
    assert manager.status()[0]["reason"] == "registration_failed"
