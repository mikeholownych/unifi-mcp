"""Validate webhook destinations against common SSRF paths."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], Awaitable[set[str]]]


async def resolve_hostname(hostname: str) -> set[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return {record[4][0] for record in records}


async def validate_webhook_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Resolver = resolve_hostname,
) -> str:
    """Return a validated webhook URL after checking its current DNS answers."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("webhook destinations must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("webhook destination URLs must not contain credentials")
    if parsed.fragment:
        raise ValueError("webhook destination URLs must not contain fragments")
    if not parsed.hostname:
        raise ValueError("webhook destination must include a hostname")

    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        try:
            addresses = await resolver(parsed.hostname)
        except OSError as exc:
            raise ValueError("webhook destination hostname could not be resolved") from exc
    else:
        addresses = {str(literal)}

    if not addresses:
        raise ValueError("webhook destination hostname did not resolve to an address")
    if not allow_private and any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("webhook destination resolves to a private or reserved address")
    return url
