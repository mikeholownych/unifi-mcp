"""MCP tools for durable local client tags and groups."""

from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.runtime.client_organization import normalize_client_key
from unifi_mcp.runtime.services import RuntimeServices


def _app(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _services(ctx: Context) -> RuntimeServices | None:
    return _app(ctx).runtime_services


def _network_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    return UniFiNetworkClient(_app(ctx), device_name=device)


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "reason": "Local client organization requires UNIFI_RUNTIME_ENABLED=true",
    }


def _confirmation(message: str) -> dict[str, Any]:
    return {"available": True, "success": False, "confirmed": False, "message": message}


def _scope(ctx: Context, client: UniFiNetworkClient, site: str) -> tuple[str, str]:
    controller = client.device.name if client.device else _app(ctx).settings.default_device_name
    return controller, site


async def _resolve_client(client: UniFiNetworkClient, identity: str, site: str) -> dict[str, Any]:
    clients = await client.get_all_clients(site)
    try:
        requested_mac = normalize_client_key(identity)
    except ValueError:
        requested_mac = None

    matches = []
    needle = identity.strip().casefold()
    for candidate in clients:
        try:
            candidate_mac = normalize_client_key(str(candidate.get("mac", "")))
        except ValueError:
            continue
        names = {
            str(candidate.get(field, "")).strip().casefold()
            for field in ("name", "hostname")
            if candidate.get(field)
        }
        if requested_mac == candidate_mac or (requested_mac is None and needle in names):
            matches.append((candidate_mac, candidate))

    unique = dict(matches)
    if not unique:
        raise ValueError("client identity did not match a known client in this controller/site")
    if len(unique) > 1:
        raise ValueError("client identity is ambiguous; use the exact client MAC address")
    client_key, candidate = next(iter(unique.items()))
    return {
        "mac": client_key,
        "name": candidate.get("name") or candidate.get("hostname") or "Unknown",
        "online": bool(candidate.get("is_online", False)),
    }


async def get_client_organization(
    ctx: Context, identity: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    client = _network_client(ctx, device)
    resolved = await _resolve_client(client, identity, site)
    controller, site = _scope(ctx, client, site)
    organization = await services.client_organization.get_client(
        controller=controller, site=site, client_key=resolved["mac"]
    )
    return {
        "available": True,
        "local_only": True,
        "client": resolved,
        "organization": organization,
    }


async def set_client_tags(
    ctx: Context,
    identity: str,
    tags: list[str],
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return _confirmation("Replacing local client tags requires confirm=true.")
    client = _network_client(ctx, device)
    resolved = await _resolve_client(client, identity, site)
    controller, site = _scope(ctx, client, site)
    organization = await services.client_organization.replace_tags(
        controller=controller, site=site, client_key=resolved["mac"], tags=tags
    )
    return {
        "available": True,
        "success": True,
        "local_only": True,
        "client": resolved,
        "organization": organization,
    }


async def create_client_group(
    ctx: Context,
    name: str,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return _confirmation("Creating a local client group requires confirm=true.")
    client = _network_client(ctx, device)
    controller, site = _scope(ctx, client, site)
    group = await services.client_organization.create_group(
        controller=controller, site=site, name=name
    )
    return {"available": True, "success": True, "local_only": True, "group": group}


async def delete_client_group(
    ctx: Context,
    name: str,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return _confirmation("Deleting a local client group requires confirm=true.")
    client = _network_client(ctx, device)
    controller, site = _scope(ctx, client, site)
    deleted = await services.client_organization.delete_group(
        controller=controller, site=site, name=name
    )
    return {"available": True, "success": deleted, "local_only": True, "name": name}


async def assign_client_group(
    ctx: Context,
    identity: str,
    group: str | None,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return _confirmation("Changing local client group membership requires confirm=true.")
    client = _network_client(ctx, device)
    resolved = await _resolve_client(client, identity, site)
    controller, site = _scope(ctx, client, site)
    organization = await services.client_organization.assign_group(
        controller=controller,
        site=site,
        client_key=resolved["mac"],
        name=group,
    )
    return {
        "available": True,
        "success": True,
        "local_only": True,
        "client": resolved,
        "organization": organization,
    }


async def list_client_groups(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    client = _network_client(ctx, device)
    controller, site = _scope(ctx, client, site)
    groups = await services.client_organization.list_groups(controller=controller, site=site)
    return {"available": True, "local_only": True, "groups": groups}


async def list_clients_by_organization(
    ctx: Context,
    tag: str | None = None,
    group: str | None = None,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    client = _network_client(ctx, device)
    controller, site = _scope(ctx, client, site)
    client_keys = await services.client_organization.list_client_keys(
        controller=controller, site=site, tag=tag, group=group
    )
    return {
        "available": True,
        "local_only": True,
        "controller": controller,
        "site": site,
        "client_keys": client_keys,
    }
