"""Tests for UniFi MCP Server configuration."""

import json

import pytest

from unifi_mcp.config import UniFiDevice, UniFiSettings


def make_settings(**kwargs) -> UniFiSettings:
    """Build settings without reading any .env file."""
    return UniFiSettings(_env_file=None, **kwargs)


class TestUniFiDevice:
    def test_api_base_urls(self):
        device = UniFiDevice(
            name="gw", url="https://10.0.0.1/", api_key="key", services=["network"]
        )
        assert device.network_api_base == "https://10.0.0.1/proxy/network/integration"
        assert device.protect_api_base == "https://10.0.0.1/proxy/protect/integration/v1"
        assert device.protect_internal_api_base == "https://10.0.0.1/proxy/protect/api"

    def test_service_flags(self):
        device = UniFiDevice(
            name="nvr", url="https://x", api_key="k", services=["network", "protect"]
        )
        assert device.has_network and device.has_protect

    def test_protect_credentials_flag(self):
        device = UniFiDevice(name="nvr", url="https://x", api_key="k")
        assert not device.has_protect_credentials
        device = UniFiDevice(
            name="nvr", url="https://x", api_key="k", username="u", password="p"
        )
        assert device.has_protect_credentials


class TestMultiDeviceConfig:
    def test_parse_devices_json(self):
        devices = [
            {
                "name": "Main Gateway",
                "url": "https://192.168.1.1",
                "api_key": "key1",
                "services": ["network"],
                "site": "default",
            },
            {
                "name": "nvr",
                "url": "https://192.168.1.2",
                "api_key": "key2",
                "services": ["network", "protect"],
                "username": "admin",
                "password": "pw",
            },
        ]
        s = make_settings(devices_json=json.dumps(devices))
        assert len(s.devices) == 2
        assert s.devices[0].api_key == "key1"
        assert s.devices[1].has_protect_credentials

    def test_legacy_single_device_fallback(self):
        s = make_settings(
            controller_url="https://192.168.1.1",
            cloud_api_key="legacy-key",
            site="default",
        )
        assert len(s.devices) == 1
        assert s.devices[0].api_key == "legacy-key"

    def test_get_device_case_insensitive(self):
        s = make_settings(
            devices_json='[{"name":"Gateway","url":"https://x","api_key":"k"}]'
        )
        assert s.get_device("gateway").name == "Gateway"
        assert s.get_device(None).name == "Gateway"
        assert s.get_device("nope") is None

    def test_service_filters(self):
        s = make_settings(
            devices_json=(
                '[{"name":"gw","url":"https://x","api_key":"k","services":["network"]},'
                '{"name":"nvr","url":"https://y","api_key":"j","services":["protect"]}]'
            )
        )
        assert [d.name for d in s.get_network_devices()] == ["gw"]
        assert [d.name for d in s.get_protect_devices()] == ["nvr"]


class TestLegacyModeProperties:
    def test_auth_url_udm(self):
        s = make_settings(
            mode="local", controller_url="https://192.168.1.1/", is_udm=True
        )
        assert s.auth_url == "https://192.168.1.1/api/auth/login"
        assert s.logout_url == "https://192.168.1.1/api/auth/logout"

    def test_auth_url_traditional(self):
        s = make_settings(
            mode="local", controller_url="https://192.168.1.1", is_udm=False
        )
        assert s.auth_url == "https://192.168.1.1/api/login"
        assert s.logout_url == "https://192.168.1.1/api/logout"

    def test_auth_url_requires_controller(self):
        s = make_settings(mode="local")
        with pytest.raises(ValueError):
            _ = s.auth_url

    def test_uses_api_key_with_devices(self):
        s = make_settings(
            devices_json='[{"name":"gw","url":"https://x","api_key":"k"}]'
        )
        assert s.uses_api_key is True

    def test_uses_api_key_false_without_key(self):
        s = make_settings(mode="local_api_key")
        assert s.uses_api_key is False

    def test_api_base_url_integration_mode(self):
        s = make_settings(
            mode="local_api_key",
            controller_url="https://192.168.1.1",
            cloud_api_key="key",
        )
        assert s.api_base_url == "https://192.168.1.1/proxy/network/integration"


class TestDevicesJsonQuoting:
    def test_strips_wrapping_quotes(self):
        raw = '\'[{"name":"gw","url":"https://x","api_key":"k"}]\''
        s = make_settings(devices_json=raw)
        assert len(s.devices) == 1
