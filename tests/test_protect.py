"""Tests for the UniFi Protect API client."""

import base64

import httpx
import pytest
import respx

from unifi_mcp.clients.protect import UniFiProtectClient
from unifi_mcp.config import UniFiDevice
from unifi_mcp.exceptions import UniFiAuthError, UniFiNotFoundError


def make_device(**overrides) -> UniFiDevice:
    data = {
        "name": "nvr",
        "url": "https://10.0.0.2",
        "api_key": "protect-key",
        "services": ["protect"],
    }
    data.update(overrides)
    return UniFiDevice(**data)


def make_client(device: UniFiDevice | None = None) -> UniFiProtectClient:
    return UniFiProtectClient(httpx.AsyncClient(), device or make_device())


CAMERAS = [
    {"id": "cam1", "name": "Front Door", "state": "CONNECTED", "type": "G4 Doorbell"},
    {"id": "cam2", "name": "Backyard", "state": "DISCONNECTED", "type": "G4 Bullet"},
]


class TestCameras:
    @respx.mock
    async def test_get_cameras(self):
        route = respx.get("https://10.0.0.2/proxy/protect/integration/v1/cameras").respond(
            json=CAMERAS
        )
        client = make_client()
        cameras = await client.get_cameras()
        assert len(cameras) == 2
        assert route.calls.last.request.headers["X-API-KEY"] == "protect-key"

    @respx.mock
    async def test_camera_by_name_partial_match(self):
        respx.get("https://10.0.0.2/proxy/protect/integration/v1/cameras").respond(
            json=CAMERAS
        )
        client = make_client()
        camera = await client.get_camera_by_name("front door")
        assert camera["id"] == "cam1"
        with pytest.raises(UniFiNotFoundError):
            await client.get_camera_by_name("garage")

    @respx.mock
    async def test_snapshot_base64(self):
        jpeg = b"\xff\xd8fakejpegdata"
        respx.get(
            "https://10.0.0.2/proxy/protect/integration/v1/cameras/cam1/snapshot"
        ).respond(content=jpeg)
        client = make_client()
        result = await client.get_camera_snapshot_base64("cam1")
        assert base64.b64decode(result) == jpeg

    @respx.mock
    async def test_camera_summary_counts(self):
        respx.get("https://10.0.0.2/proxy/protect/integration/v1/cameras").respond(
            json=CAMERAS
        )
        client = make_client()
        summary = await client.get_camera_summary()
        assert summary["total_cameras"] == 2
        assert summary["connected"] == 1
        assert summary["disconnected"] == 1


class TestSessionAuth:
    @respx.mock
    async def test_events_require_credentials(self):
        client = make_client(make_device())
        with pytest.raises(UniFiAuthError, match="Username and password required"):
            await client.get_events()

    @respx.mock
    async def test_session_login_then_events(self):
        device = make_device(username="admin", password="secret")
        login_route = respx.post("https://10.0.0.2/api/auth/login").respond(
            200, headers={"X-CSRF-Token": "csrf-123"}
        )
        events_route = respx.get("https://10.0.0.2/proxy/protect/api/events").respond(
            json=[{"id": "e1", "type": "motion", "camera": "cam1", "start": 1700000000000}]
        )

        client = make_client(device)
        events = await client.get_motion_events(hours=1)

        assert login_route.called
        assert len(events) == 1
        assert events[0]["type"] == "motion"
        # Session headers (CSRF) applied to internal API calls
        assert events_route.calls.last.request.headers["X-CSRF-Token"] == "csrf-123"

    @respx.mock
    async def test_bad_credentials_raise(self):
        device = make_device(username="admin", password="wrong")
        respx.post("https://10.0.0.2/api/auth/login").respond(401)

        client = make_client(device)
        with pytest.raises(UniFiAuthError, match="Invalid username or password"):
            await client.get_motion_events()


class TestEventSummary:
    @respx.mock
    async def test_event_summary_categorization(self):
        device = make_device(username="a", password="b")
        now_ms = 1700000000000
        respx.post("https://10.0.0.2/api/auth/login").respond(200)
        respx.get("https://10.0.0.2/proxy/protect/api/events").respond(
            json=[
                {"id": "1", "type": "motion", "camera": "cam1", "start": now_ms},
                {
                    "id": "2",
                    "type": "smartDetect",
                    "camera": "cam1",
                    "start": now_ms,
                    "smartDetectTypes": ["person"],
                },
                {"id": "3", "type": "ring", "camera": "cam1", "start": now_ms},
            ]
        )
        respx.get("https://10.0.0.2/proxy/protect/integration/v1/cameras").respond(
            json=CAMERAS
        )

        client = make_client(device)
        summary = await client.get_event_summary(hours=24)

        assert summary["total_events"] == 3
        assert summary["motion_events"] == 1
        assert summary["smart_detections"] == 1
        assert summary["doorbell_rings"] == 1
        assert summary["smart_detection_breakdown"]["person"] == 1
