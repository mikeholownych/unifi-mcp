"""Package version metadata."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed distribution version."""
    try:
        return version("mcp-unifi")
    except PackageNotFoundError:
        return "0+unknown"
