"""Local controller authentication for UniFi OS and traditional controllers."""

import logging

import httpx

from unifi_mcp.config import UniFiSettings
from unifi_mcp.exceptions import UniFiAuthError, UniFiConnectionError

logger = logging.getLogger(__name__)


class UniFiLocalAuth:
    """Handles authentication for local UniFi controllers.

    Supports both UniFi OS devices (UDM, UDM-Pro, UCG-Fiber) and
    traditional UniFi Controller software.
    """

    def __init__(self, client: httpx.AsyncClient, settings: UniFiSettings):
        """Initialize the auth handler.

        Args:
            client: httpx AsyncClient instance for making requests
            settings: UniFi settings configuration
        """
        self.client = client
        self.settings = settings
        self._csrf_token: str | None = None
        self._is_authenticated = False

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self._is_authenticated

    @property
    def csrf_token(self) -> str | None:
        """Get the current CSRF token (for UniFi OS)."""
        return self._csrf_token

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers required for authenticated requests."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # UniFi OS requires CSRF token for certain operations
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token

        return headers

    async def login(self) -> bool:
        """Authenticate with the UniFi controller.

        Returns:
            True if authentication was successful

        Raises:
            UniFiAuthError: If authentication fails
            UniFiConnectionError: If unable to connect to controller
        """
        if not self.settings.username or not self.settings.password:
            raise UniFiAuthError("Username and password are required for local authentication")

        auth_url = self.settings.auth_url
        payload = {
            "username": self.settings.username,
            "password": self.settings.password,
        }

        logger.debug(f"Authenticating with UniFi controller at {auth_url}")

        try:
            response = await self.client.post(
                auth_url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        except httpx.ConnectError as e:
            raise UniFiConnectionError(f"Failed to connect to controller: {e}") from e
        except httpx.TimeoutException as e:
            raise UniFiConnectionError(f"Connection timed out: {e}") from e

        if response.status_code == 200:
            self._is_authenticated = True

            # UniFi OS returns CSRF token in response header
            if "X-CSRF-Token" in response.headers:
                self._csrf_token = response.headers["X-CSRF-Token"]
                logger.debug("CSRF token obtained")

            logger.info("Successfully authenticated with UniFi controller")
            return True

        if response.status_code == 401:
            raise UniFiAuthError("Invalid username or password")

        if response.status_code == 403:
            raise UniFiAuthError("Access forbidden - check user permissions")

        # Try to extract error message from response
        try:
            data = response.json()
            error_msg = data.get("meta", {}).get("msg", "Unknown error")
            raise UniFiAuthError(f"Authentication failed: {error_msg}") from None
        except Exception:
            raise UniFiAuthError(f"Authentication failed with status {response.status_code}") from None

    async def logout(self) -> None:
        """Log out from the UniFi controller."""
        if not self._is_authenticated:
            return

        logout_url = self.settings.logout_url

        try:
            await self.client.post(logout_url, headers=self._get_auth_headers())
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
        finally:
            self._is_authenticated = False
            self._csrf_token = None
            logger.info("Logged out from UniFi controller")

    async def refresh_session(self) -> bool:
        """Refresh the authentication session.

        Attempts to re-authenticate if the session has expired.

        Returns:
            True if session was refreshed successfully

        Raises:
            UniFiAuthError: If refresh fails
        """
        logger.debug("Refreshing authentication session")
        self._is_authenticated = False
        self._csrf_token = None

        return await self.login()

    async def ensure_authenticated(self) -> None:
        """Ensure we have a valid authentication session.

        Logs in if not already authenticated.

        Raises:
            UniFiAuthError: If authentication fails
        """
        if not self._is_authenticated:
            await self.login()

    async def check_session(self) -> bool:
        """Check if the current session is still valid.

        Returns:
            True if session is valid, False otherwise
        """
        if not self._is_authenticated:
            return False

        # Try to access self endpoint to verify session
        base_url = self.settings.api_base_url
        check_url = f"{base_url}/api/self"

        try:
            response = await self.client.get(check_url, headers=self._get_auth_headers())
            return response.status_code == 200
        except Exception:
            return False

    def get_request_headers(self) -> dict[str, str]:
        """Get headers for authenticated API requests.

        Returns:
            Dictionary of headers including auth-related headers
        """
        return self._get_auth_headers()


class UniFiCloudAuth:
    """Handles authentication for Ubiquiti Cloud API (api.ui.com)."""

    def __init__(self, api_key: str):
        """Initialize cloud auth with API key.

        Args:
            api_key: API key from unifi.ui.com
        """
        self.api_key = api_key

    def get_request_headers(self) -> dict[str, str]:
        """Get headers for authenticated API requests.

        Returns:
            Dictionary of headers including API key
        """
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key,
        }

    @property
    def is_authenticated(self) -> bool:
        """Cloud auth is always authenticated if API key is present."""
        return bool(self.api_key)

    async def ensure_authenticated(self) -> None:
        """Verify API key is configured."""
        if not self.api_key:
            raise UniFiAuthError("Cloud API key is required")
