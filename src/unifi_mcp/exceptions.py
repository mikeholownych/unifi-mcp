"""Custom exceptions for UniFi MCP Server."""


class UniFiError(Exception):
    """Base exception for all UniFi errors."""

    pass


class UniFiAuthError(UniFiError):
    """Authentication failed.

    Raised when:
    - Invalid credentials provided
    - Session expired and refresh failed
    - API key is invalid (cloud mode)
    """

    pass


class UniFiConfigError(UniFiError):
    """Invalid or missing configuration.

    Raised when required settings are absent or contradictory.
    """

    pass


class UniFiConnectionError(UniFiError):
    """Cannot connect to the UniFi controller.

    Raised when:
    - Network is unreachable
    - Controller is offline
    - DNS resolution failed
    - Connection timeout
    """

    pass


class UniFiAPIError(UniFiError):
    """API returned an error response.

    Raised when the API returns an error status code or error message.
    """

    def __init__(self, message: str, status_code: int | None = None, response_data: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.status_code}] {super().__str__()}"
        return super().__str__()


class UniFiRateLimitError(UniFiAPIError):
    """Rate limit exceeded.

    Raised when the API returns a 429 status code.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class UniFiNotFoundError(UniFiAPIError):
    """Resource not found.

    Raised when requesting a device, client, or other resource that doesn't exist.
    """

    def __init__(self, resource_type: str, identifier: str):
        message = f"{resource_type} not found: {identifier}"
        super().__init__(message, status_code=404)
        self.resource_type = resource_type
        self.identifier = identifier
