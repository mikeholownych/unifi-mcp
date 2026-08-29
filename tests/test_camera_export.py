"""Confirmation and confinement for Protect camera clip exports."""

from types import SimpleNamespace

import pytest

from unifi_mcp.tools.protect import cameras


def context_for(tmp_path):
    app = SimpleNamespace(settings=SimpleNamespace(export_directory=tmp_path))
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


class FakeProtectClient:
    def __init__(self):
        self.export_calls = 0

    async def get_cameras(self):
        return [{"id": "camera-1", "name": "Front"}]

    async def export_camera_clip(self, _camera_id, _start, _end):
        self.export_calls += 1
        return b"video"


async def test_camera_export_requires_confirmation_before_controller_call(tmp_path, monkeypatch):
    client = FakeProtectClient()
    monkeypatch.setattr(cameras, "_get_protect_client", lambda *_args: client)

    result = await cameras.export_camera_clip(context_for(tmp_path), "Front", 1, 2, "clip.mp4")

    assert result["success"] is False
    assert client.export_calls == 0


async def test_camera_export_rejects_unconfined_path_before_controller_call(tmp_path, monkeypatch):
    client = FakeProtectClient()
    monkeypatch.setattr(cameras, "_get_protect_client", lambda *_args: client)

    with pytest.raises(ValueError, match="plain filename"):
        await cameras.export_camera_clip(
            context_for(tmp_path), "Front", 1, 2, "../clip.mp4", confirm=True
        )

    assert client.export_calls == 0


async def test_camera_export_writes_private_confined_file(tmp_path, monkeypatch):
    client = FakeProtectClient()
    monkeypatch.setattr(cameras, "_get_protect_client", lambda *_args: client)

    result = await cameras.export_camera_clip(
        context_for(tmp_path), "Front", 1, 2, "clip.mp4", confirm=True
    )

    assert result["success"] is True
    assert result["file"] == str(tmp_path / "clip.mp4")
    assert (tmp_path / "clip.mp4").read_bytes() == b"video"
    assert (tmp_path / "clip.mp4").stat().st_mode & 0o777 == 0o600
