"""UniFi Protect API client."""

import base64
import logging
import time
from typing import Any

import httpx

from unifi_mcp.config import UniFiDevice
from unifi_mcp.exceptions import (
    UniFiAPIError,
    UniFiAuthError,
    UniFiConnectionError,
    UniFiNotFoundError,
)

logger = logging.getLogger(__name__)


class UniFiProtectClient:
    """Client for UniFi Protect API.

    Provides methods for managing cameras, viewing events, and accessing
    NVR functionality via both:
    - Integration API (v1): Uses API key auth for basic camera operations
    - Internal API: Uses session auth for events, recordings, and advanced features

    The Integration API is used by default. Session auth is required for
    events and recordings, and will be established automatically if
    credentials are configured.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        device: UniFiDevice,
    ):
        """Initialize the Protect API client.

        Args:
            client: httpx AsyncClient instance
            device: UniFi device configuration
        """
        self.client = client
        self.device = device
        self.base_url = device.protect_api_base
        self.internal_base_url = device.protect_internal_api_base
        self._csrf_token: str | None = None
        self._session_authenticated = False

    @property
    def _headers(self) -> dict[str, str]:
        """Get headers for Integration API requests."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": self.device.api_key,
        }

    @property
    def _session_headers(self) -> dict[str, str]:
        """Get headers for session-authenticated requests."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        return headers

    async def _ensure_session_auth(self) -> None:
        """Ensure session authentication is established.

        Required for events and recordings access.

        Raises:
            UniFiAuthError: If credentials not configured or auth fails
        """
        if self._session_authenticated:
            return

        if not self.device.has_protect_credentials:
            raise UniFiAuthError(
                "Username and password required for Protect events/recordings. "
                "Add 'username' and 'password' to your device configuration."
            )

        auth_url = f"{self.device.url.rstrip('/')}/api/auth/login"
        payload = {
            "username": self.device.username,
            "password": self.device.password,
        }

        try:
            response = await self.client.post(
                auth_url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        except httpx.ConnectError as e:
            raise UniFiConnectionError(f"Failed to connect for auth: {e}") from e

        if response.status_code == 200:
            self._session_authenticated = True
            if "X-CSRF-Token" in response.headers:
                self._csrf_token = response.headers["X-CSRF-Token"]
            logger.info("Session authentication established for Protect")
        elif response.status_code == 401:
            raise UniFiAuthError("Invalid username or password for Protect")
        else:
            raise UniFiAuthError(f"Protect auth failed with status {response.status_code}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional arguments for httpx

        Returns:
            HTTP response

        Raises:
            UniFiConnectionError: If connection fails
            UniFiAPIError: For API errors
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = await self.client.request(
                method,
                url,
                headers=self._headers,
                **kwargs,
            )
        except httpx.ConnectError as e:
            raise UniFiConnectionError(f"Failed to connect to Protect: {e}") from e
        except httpx.TimeoutException as e:
            raise UniFiConnectionError(f"Request timed out: {e}") from e

        if response.status_code == 401:
            raise UniFiAPIError("Authentication failed", 401)
        if response.status_code == 404:
            raise UniFiNotFoundError("Resource", endpoint)
        if response.status_code >= 400:
            raise UniFiAPIError(
                f"API error: {response.text[:200]}",
                response.status_code,
            )

        return response

    async def _get(self, endpoint: str, **kwargs: Any) -> Any:
        """Make a GET request and return JSON."""
        response = await self._request("GET", endpoint, **kwargs)
        return response.json()

    async def _get_binary(self, endpoint: str, **kwargs: Any) -> bytes:
        """Make a GET request and return binary data."""
        response = await self._request("GET", endpoint, **kwargs)
        return response.content

    # =========================================================================
    # Cameras
    # =========================================================================

    async def get_cameras(self) -> list[dict[str, Any]]:
        """Get all cameras.

        Returns:
            List of camera information dictionaries
        """
        return await self._get("/cameras")

    async def get_camera(self, camera_id: str) -> dict[str, Any]:
        """Get details for a specific camera.

        Args:
            camera_id: Camera ID

        Returns:
            Camera information dictionary

        Raises:
            UniFiNotFoundError: If camera not found
        """
        return await self._get(f"/cameras/{camera_id}")

    async def get_camera_by_name(self, name: str) -> dict[str, Any]:
        """Get a camera by name.

        Args:
            name: Camera name (case-insensitive partial match)

        Returns:
            Camera information dictionary

        Raises:
            UniFiNotFoundError: If camera not found
        """
        cameras = await self.get_cameras()
        name_lower = name.lower()

        for camera in cameras:
            if name_lower in camera.get("name", "").lower():
                return camera

        raise UniFiNotFoundError("Camera", name)

    async def get_camera_snapshot(
        self,
        camera_id: str,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Get a snapshot from a camera.

        Args:
            camera_id: Camera ID
            width: Optional width for resizing
            height: Optional height for resizing

        Returns:
            JPEG image bytes
        """
        params = {}
        if width:
            params["w"] = width
        if height:
            params["h"] = height

        return await self._get_binary(f"/cameras/{camera_id}/snapshot", params=params)

    async def get_camera_snapshot_base64(
        self,
        camera_id: str,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        """Get a snapshot from a camera as base64.

        Args:
            camera_id: Camera ID
            width: Optional width for resizing
            height: Optional height for resizing

        Returns:
            Base64-encoded JPEG image
        """
        image_bytes = await self.get_camera_snapshot(camera_id, width, height)
        return base64.b64encode(image_bytes).decode("utf-8")

    # =========================================================================
    # Liveviews
    # =========================================================================

    async def get_liveviews(self) -> list[dict[str, Any]]:
        """Get all liveviews.

        Returns:
            List of liveview configurations
        """
        return await self._get("/liveviews")

    # =========================================================================
    # Sensors & Accessories
    # =========================================================================

    async def get_lights(self) -> list[dict[str, Any]]:
        """Get all Protect lights (floodlights).

        Returns:
            List of light information
        """
        return await self._get("/lights")

    async def get_sensors(self) -> list[dict[str, Any]]:
        """Get all Protect sensors.

        Returns:
            List of sensor information
        """
        return await self._get("/sensors")

    async def get_chimes(self) -> list[dict[str, Any]]:
        """Get all Protect chimes.

        Returns:
            List of chime information
        """
        return await self._get("/chimes")

    async def get_viewers(self) -> list[dict[str, Any]]:
        """Get all Protect viewers (Viewport devices).

        Returns:
            List of viewer information
        """
        return await self._get("/viewers")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def get_camera_summary(self) -> dict[str, Any]:
        """Get a summary of all cameras with status.

        Returns:
            Summary with camera counts and details
        """
        cameras = await self.get_cameras()

        connected = [c for c in cameras if c.get("state") == "CONNECTED"]
        disconnected = [c for c in cameras if c.get("state") == "DISCONNECTED"]

        return {
            "total_cameras": len(cameras),
            "connected": len(connected),
            "disconnected": len(disconnected),
            "cameras": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "state": c.get("state"),
                    "model": c.get("type") or c.get("modelKey"),
                    "mac": c.get("mac"),
                    "is_mic_enabled": c.get("isMicEnabled"),
                    "is_recording": c.get("isRecording"),
                }
                for c in cameras
            ],
        }

    async def get_system_info(self) -> dict[str, Any]:
        """Get Protect system information.

        Returns:
            System info including camera/sensor counts
        """
        cameras = await self.get_cameras()
        lights = await self.get_lights()
        sensors = await self.get_sensors()
        chimes = await self.get_chimes()
        viewers = await self.get_viewers()
        liveviews = await self.get_liveviews()

        connected_cams = [c for c in cameras if c.get("state") == "CONNECTED"]

        return {
            "device_name": self.device.name,
            "device_url": self.device.url,
            "cameras": {
                "total": len(cameras),
                "connected": len(connected_cams),
                "disconnected": len(cameras) - len(connected_cams),
            },
            "accessories": {
                "lights": len(lights),
                "sensors": len(sensors),
                "chimes": len(chimes),
                "viewers": len(viewers),
            },
            "liveviews": len(liveviews),
            "events_available": self.device.has_protect_credentials,
        }

    # =========================================================================
    # Internal API (requires session auth)
    # =========================================================================

    async def _internal_request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request to the internal Protect API.

        Requires session authentication (username/password).

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional arguments for httpx

        Returns:
            HTTP response

        Raises:
            UniFiAuthError: If credentials not configured
            UniFiConnectionError: If connection fails
            UniFiAPIError: For API errors
        """
        await self._ensure_session_auth()

        url = f"{self.internal_base_url}{endpoint}"

        try:
            response = await self.client.request(
                method,
                url,
                headers=self._session_headers,
                **kwargs,
            )
        except httpx.ConnectError as e:
            raise UniFiConnectionError(f"Failed to connect to Protect: {e}") from e
        except httpx.TimeoutException as e:
            raise UniFiConnectionError(f"Request timed out: {e}") from e

        if response.status_code == 401:
            # Session may have expired, try to re-auth
            self._session_authenticated = False
            await self._ensure_session_auth()
            response = await self.client.request(
                method,
                url,
                headers=self._session_headers,
                **kwargs,
            )

        if response.status_code == 401:
            raise UniFiAPIError("Authentication failed", 401)
        if response.status_code == 404:
            raise UniFiNotFoundError("Resource", endpoint)
        if response.status_code >= 400:
            raise UniFiAPIError(
                f"API error: {response.text[:200]}",
                response.status_code,
            )

        return response

    async def _internal_get(self, endpoint: str, **kwargs: Any) -> Any:
        """Make a GET request to internal API and return JSON."""
        response = await self._internal_request("GET", endpoint, **kwargs)
        return response.json()

    # =========================================================================
    # Events (requires session auth)
    # =========================================================================

    async def get_events(
        self,
        start: int | None = None,
        end: int | None = None,
        limit: int = 100,
        camera_ids: list[str] | None = None,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get motion and detection events.

        Requires session authentication (username/password configured).

        Args:
            start: Start timestamp in milliseconds (default: 24 hours ago)
            end: End timestamp in milliseconds (default: now)
            limit: Maximum number of events to return (default: 100)
            camera_ids: Filter by camera IDs
            types: Filter by event types (motion, smartDetect, ring, etc.)

        Returns:
            List of event dictionaries

        Raises:
            UniFiAuthError: If credentials not configured
        """
        if end is None:
            end = int(time.time() * 1000)
        if start is None:
            start = end - (24 * 60 * 60 * 1000)  # 24 hours ago

        params = {
            "start": start,
            "end": end,
            "limit": limit,
        }

        if camera_ids:
            params["cameras"] = ",".join(camera_ids)
        if types:
            params["types"] = ",".join(types)

        return await self._internal_get("/events", params=params)

    async def get_motion_events(
        self,
        hours: int = 24,
        limit: int = 100,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get motion detection events.

        Convenience method for getting motion events.

        Args:
            hours: Number of hours to look back (default: 24)
            limit: Maximum number of events
            camera_id: Filter to specific camera

        Returns:
            List of motion events
        """
        end = int(time.time() * 1000)
        start = end - (hours * 60 * 60 * 1000)

        camera_ids = [camera_id] if camera_id else None
        events = await self.get_events(
            start=start,
            end=end,
            limit=limit,
            camera_ids=camera_ids,
            types=["motion"],
        )

        return events

    async def get_smart_detection_events(
        self,
        hours: int = 24,
        limit: int = 100,
        camera_id: str | None = None,
        detection_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get smart detection events (person, vehicle, animal, package).

        Args:
            hours: Number of hours to look back (default: 24)
            limit: Maximum number of events
            camera_id: Filter to specific camera
            detection_types: Filter by detection type (person, vehicle, animal, package)

        Returns:
            List of smart detection events
        """
        end = int(time.time() * 1000)
        start = end - (hours * 60 * 60 * 1000)

        camera_ids = [camera_id] if camera_id else None
        events = await self.get_events(
            start=start,
            end=end,
            limit=limit,
            camera_ids=camera_ids,
            types=["smartDetect"],
        )

        # Filter by detection type if specified
        if detection_types:
            events = [
                e for e in events
                if any(dt in e.get("smartDetectTypes", []) for dt in detection_types)
            ]

        return events

    async def get_event_thumbnail(self, event_id: str) -> bytes:
        """Get thumbnail image for an event.

        Args:
            event_id: Event ID

        Returns:
            JPEG image bytes
        """
        response = await self._internal_request(
            "GET",
            f"/events/{event_id}/thumbnail",
        )
        return response.content

    async def get_event_thumbnail_base64(self, event_id: str) -> str:
        """Get thumbnail image for an event as base64.

        Args:
            event_id: Event ID

        Returns:
            Base64-encoded JPEG image
        """
        image_bytes = await self.get_event_thumbnail(event_id)
        return base64.b64encode(image_bytes).decode("utf-8")

    async def get_event_animated_thumbnail(self, event_id: str) -> bytes:
        """Get animated thumbnail (GIF) for an event.

        Args:
            event_id: Event ID

        Returns:
            GIF image bytes
        """
        response = await self._internal_request(
            "GET",
            f"/events/{event_id}/animated-thumbnail",
        )
        return response.content

    # =========================================================================
    # Event Summary Helpers
    # =========================================================================

    async def get_event_summary(
        self,
        hours: int = 24,
        camera_id: str | None = None,
    ) -> dict[str, Any]:
        """Get a summary of events for the specified time period.

        Args:
            hours: Number of hours to look back
            camera_id: Filter to specific camera

        Returns:
            Event summary with counts by type
        """
        end = int(time.time() * 1000)
        start = end - (hours * 60 * 60 * 1000)

        camera_ids = [camera_id] if camera_id else None

        # Get all events
        events = await self.get_events(
            start=start,
            end=end,
            limit=1000,
            camera_ids=camera_ids,
        )

        # Categorize events
        motion_count = 0
        smart_detect_count = 0
        ring_count = 0
        other_count = 0

        smart_detect_breakdown = {
            "person": 0,
            "vehicle": 0,
            "animal": 0,
            "package": 0,
        }

        cameras_with_events = set()

        for event in events:
            event_type = event.get("type", "").lower()
            camera = event.get("camera")
            if camera:
                cameras_with_events.add(camera)

            if event_type == "motion":
                motion_count += 1
            elif event_type == "smartdetect":
                smart_detect_count += 1
                for detect_type in event.get("smartDetectTypes", []):
                    if detect_type in smart_detect_breakdown:
                        smart_detect_breakdown[detect_type] += 1
            elif event_type == "ring":
                ring_count += 1
            else:
                other_count += 1

        return {
            "period_hours": hours,
            "total_events": len(events),
            "motion_events": motion_count,
            "smart_detections": smart_detect_count,
            "doorbell_rings": ring_count,
            "other_events": other_count,
            "smart_detection_breakdown": smart_detect_breakdown,
            "cameras_with_activity": len(cameras_with_events),
            "filtered_camera": camera_id,
        }

    async def get_recent_activity(
        self,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get recent activity across all cameras.

        Returns a simplified list of recent events for quick overview.

        Args:
            limit: Maximum number of events

        Returns:
            List of simplified event info
        """
        events = await self.get_events(limit=limit)

        # Get camera names for better readability
        cameras = await self.get_cameras()
        camera_names = {c.get("id"): c.get("name") for c in cameras}

        result = []
        for event in events:
            camera_id = event.get("camera")
            event_time = event.get("start", event.get("timestamp", 0))

            # Convert timestamp to readable format
            if event_time:
                from datetime import datetime
                dt = datetime.fromtimestamp(event_time / 1000)
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_str = "Unknown"

            result.append({
                "id": event.get("id"),
                "type": event.get("type"),
                "camera": camera_names.get(camera_id, camera_id),
                "camera_id": camera_id,
                "time": time_str,
                "timestamp": event_time,
                "smart_detect_types": event.get("smartDetectTypes", []),
                "score": event.get("score"),
            })

        return result
