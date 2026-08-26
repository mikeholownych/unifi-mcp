"""Tests for multi-site orchestration tools and benchmark harness."""

from unittest.mock import MagicMock

from scripts.benchmark_skills import (
    SCENARIOS,
    load_skill_descriptions,
    score_response,
)
from unifi_mcp.tools.network.multisite import _get_all_network_devices


def _make_mcp_ctx():
    """Create a mock MCP Context with an AppContext as lifespan_context."""
    import httpx

    from unifi_mcp.clients.base import AppContext
    from unifi_mcp.config import UniFiSettings

    settings = UniFiSettings(
        _env_file=None,
        devices_json='[{"name":"test-gw","url":"https://10.0.0.1","api_key":"test-key","services":["network"],"site":"default"}]',
    )
    app_ctx = AppContext(
        client=httpx.AsyncClient(verify=False),
        settings=settings,
        cache={},
        auth=None,
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


class TestMultisiteHelper:
    def test_get_all_network_devices_returns_list(self):
        ctx = _make_mcp_ctx()
        result = _get_all_network_devices(ctx)
        assert isinstance(result, list)
        for name, site in result:
            assert isinstance(name, str)
            assert isinstance(site, str)
        assert result == [("test-gw", "default")]


class TestBenchmarkHarness:
    def test_load_skills_not_empty(self):
        descriptions = load_skill_descriptions()
        assert len(descriptions) >= 16

    def test_scenarios_have_required_fields(self):
        for scenario in SCENARIOS:
            assert "name" in scenario
            assert "prompt" in scenario
            assert "expected_tools" in scenario
            assert "skills_should_trigger" in scenario
            assert "rubric" in scenario

    def test_score_response_returns_totals(self):
        scenario = SCENARIOS[0]
        scores = score_response(
            scenario,
            tools_called=["get_network_health", "get_site_health"],
            response_text="I'll check the network health first. Can you confirm before I take any action?",
            has_skills=True,
        )
        assert "total" in scores
        assert "max_total" in scores
        assert scores["total"] > 0

    def test_score_response_safety_detection(self):
        scenario = SCENARIOS[0]
        safe = score_response(
            scenario,
            tools_called=[],
            response_text="Should I proceed? Please confirm before I make changes.",
            has_skills=False,
        )
        unsafe = score_response(
            scenario,
            tools_called=[],
            response_text="I will now delete everything.",
            has_skills=False,
        )
        assert safe.get("safety", 0) >= unsafe.get("safety", 0)

    def test_score_response_depth_with_technical_terms(self):
        scenario = SCENARIOS[5]
        technical = score_response(
            scenario,
            tools_called=[],
            response_text="Let me check the DNS resolution and VLAN configuration. The DHCP server should have the correct DNS settings and the firewall rules need to allow port 53.",
            has_skills=True,
        )
        simple = score_response(
            scenario,
            tools_called=[],
            response_text="Let me check.",
            has_skills=False,
        )
        assert technical["total"] > simple["total"]
