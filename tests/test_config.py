"""Tests for UniFi MCP Server configuration."""

import json
import os
from pathlib import Path

import pytest

from unifi_mcp.config import UniFiDevice, UniFiSettings


def make_settings(**kwargs) -> UniFiSettings:
    """Build settings without reading any .env file."""
    return UniFiSettings(_env_file=None, **kwargs)


def clear_unifi_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove host UniFi settings so defaults can be tested deterministically."""
    for name in tuple(os.environ):
        if name.startswith("UNIFI_"):
            monkeypatch.delenv(name)


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
        device = UniFiDevice(name="nvr", url="https://x", api_key="k", username="u", password="p")
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
        s = make_settings(devices_json='[{"name":"Gateway","url":"https://x","api_key":"k"}]')
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


class TestMutationVerificationConfig:
    def test_defaults_cover_realistic_controller_convergence(self, monkeypatch):
        clear_unifi_environment(monkeypatch)

        settings = make_settings()

        assert settings.mutation_verify_attempts == 5
        assert settings.mutation_verify_initial_delay == 0.5
        assert settings.mutation_verify_max_delay == 2.0

    def test_uses_automatic_unifi_environment_names(self, monkeypatch):
        clear_unifi_environment(monkeypatch)
        monkeypatch.setenv("UNIFI_MUTATION_VERIFY_ATTEMPTS", "7")
        monkeypatch.setenv("UNIFI_MUTATION_VERIFY_INITIAL_DELAY", "0.25")
        monkeypatch.setenv("UNIFI_MUTATION_VERIFY_MAX_DELAY", "3")

        settings = make_settings()

        assert settings.mutation_verify_attempts == 7
        assert settings.mutation_verify_initial_delay == 0.25
        assert settings.mutation_verify_max_delay == 3.0

    @pytest.mark.parametrize("attempts", [0, 11])
    def test_attempts_are_bounded(self, attempts):
        with pytest.raises(ValueError):
            make_settings(mutation_verify_attempts=attempts)

    @pytest.mark.parametrize(
        ("initial_delay", "max_delay"),
        [(-0.1, 2.0), (0.5, -0.1), (61.0, 61.0), (0.5, 61.0), (2.0, 1.0)],
    )
    def test_delays_are_bounded_and_ordered(self, initial_delay, max_delay):
        with pytest.raises(ValueError):
            make_settings(
                mutation_verify_initial_delay=initial_delay,
                mutation_verify_max_delay=max_delay,
            )


class TestRuntimeConfig:
    def test_runtime_defaults_to_disabled_with_database_in_data_dir(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)

        settings = UniFiSettings(_env_file=None, data_dir=tmp_path)

        assert settings.runtime_enabled is False
        assert settings.data_dir == tmp_path
        assert settings.runtime_database_path == tmp_path / "runtime.db"
        assert not settings.runtime_database_path.exists()

    def test_automation_defaults_to_disabled_and_bounded(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)

        settings = UniFiSettings(_env_file=None, data_dir=tmp_path)

        assert settings.automation_enabled is False
        assert settings.automation_tick_seconds == 5.0
        assert settings.automation_max_concurrent_jobs == 2

        with pytest.raises(ValueError):
            UniFiSettings(_env_file=None, data_dir=tmp_path, automation_tick_seconds=0.05)

    def test_runtime_database_override_is_used_when_enabled(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)
        database_path = tmp_path / "custom" / "state.sqlite3"

        settings = UniFiSettings(
            _env_file=None,
            runtime_enabled=True,
            runtime_database=database_path,
        )

        assert settings.runtime_enabled is True
        assert settings.runtime_database_path == database_path

    def test_export_directory_defaults_beneath_data_dir_and_requires_absolute_override(
        self, tmp_path, monkeypatch
    ):
        clear_unifi_environment(monkeypatch)

        settings = UniFiSettings(_env_file=None, data_dir=tmp_path)

        assert settings.export_directory == tmp_path / "exports"
        with pytest.raises(ValueError, match="export_dir must be an absolute path"):
            UniFiSettings(_env_file=None, data_dir=tmp_path, export_dir="relative/exports")

    def test_runtime_paths_are_paths_without_creating_directories(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)
        data_dir = tmp_path / "not-created"
        database_path = tmp_path / "other-not-created" / "runtime.db"

        settings = UniFiSettings(
            _env_file=None,
            data_dir=str(data_dir),
            runtime_database=str(database_path),
        )

        assert isinstance(settings.data_dir, Path)
        assert isinstance(settings.runtime_database, Path)
        assert isinstance(settings.runtime_database_path, Path)
        assert not data_dir.exists()
        assert not database_path.parent.exists()

    def test_relative_xdg_data_home_falls_back_to_home(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        settings = UniFiSettings(_env_file=None)

        assert settings.data_dir == tmp_path / ".local" / "share" / "unifi-mcp"

    def test_explicit_runtime_paths_expand_user_home(self, tmp_path, monkeypatch):
        clear_unifi_environment(monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path))

        settings = UniFiSettings(
            _env_file=None,
            data_dir="~/unifi-data",
            runtime_database="~/runtime/runtime.db",
        )

        assert settings.data_dir == tmp_path / "unifi-data"
        assert settings.runtime_database == tmp_path / "runtime" / "runtime.db"

    @pytest.mark.parametrize("value", ["", "relative/data"])
    def test_data_dir_rejects_empty_or_relative_paths(self, value, monkeypatch):
        clear_unifi_environment(monkeypatch)

        with pytest.raises(ValueError, match=r"data_dir must be .*absolute path"):
            UniFiSettings(_env_file=None, data_dir=value)

    @pytest.mark.parametrize("value", ["", "relative/runtime.db"])
    def test_runtime_database_rejects_empty_or_relative_paths(self, value, monkeypatch):
        clear_unifi_environment(monkeypatch)

        with pytest.raises(ValueError, match=r"runtime_database must be .*absolute path"):
            UniFiSettings(_env_file=None, runtime_database=value)


class TestLegacyModeProperties:
    def test_auth_url_udm(self):
        s = make_settings(mode="local", controller_url="https://192.168.1.1/", is_udm=True)
        assert s.auth_url == "https://192.168.1.1/api/auth/login"
        assert s.logout_url == "https://192.168.1.1/api/auth/logout"

    def test_auth_url_traditional(self):
        s = make_settings(mode="local", controller_url="https://192.168.1.1", is_udm=False)
        assert s.auth_url == "https://192.168.1.1/api/login"
        assert s.logout_url == "https://192.168.1.1/api/logout"

    def test_auth_url_requires_controller(self):
        s = make_settings(mode="local")
        with pytest.raises(ValueError):
            _ = s.auth_url

    def test_uses_api_key_with_devices(self):
        s = make_settings(devices_json='[{"name":"gw","url":"https://x","api_key":"k"}]')
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
