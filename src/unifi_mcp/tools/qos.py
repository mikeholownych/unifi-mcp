"""Capability-gated client QoS planning tools."""

from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.runtime.services import RuntimeServices
from unifi_mcp.tools.client_organization import (
    _app,
    _resolve_client,
    _scope,
)


def _services(ctx: Context) -> RuntimeServices | None:
    return _app(ctx).runtime_services


def _network_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    return UniFiNetworkClient(_app(ctx), device_name=device)


def _capabilities(ctx: Context, device: str | None = None) -> dict[str, Any]:
    return {
        "supported": False,
        "mutation_available": False,
        "device": device,
        "configured_mode": _app(ctx).settings.mode,
        "detection": "no_validated_adapter",
        "adapter": None,
        "guidance": (
            "No validated controller QoS API adapter is available in this release. "
            "Policy previews are local and apply performs no controller mutation."
        ),
    }


async def get_client_qos_capabilities(ctx: Context, device: str | None = None) -> dict[str, Any]:
    return {"available": True, **_capabilities(ctx, device)}


async def plan_client_qos_policy(
    ctx: Context,
    selector_type: str,
    selector_value: str,
    download_kbps: int,
    upload_kbps: int,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return {
            "available": False,
            "reason": "Durable QoS previews require UNIFI_RUNTIME_ENABLED=true",
        }
    client = _network_client(ctx, device)
    controller, site = _scope(ctx, client, site)
    if selector_type == "client":
        resolved = await _resolve_client(client, selector_value, site)
        client_keys = [resolved["mac"]]
    elif selector_type == "tag":
        client_keys = await services.client_organization.list_client_keys(
            controller=controller, site=site, tag=selector_value
        )
    elif selector_type == "group":
        client_keys = await services.client_organization.list_client_keys(
            controller=controller, site=site, group=selector_value
        )
    else:
        raise ValueError("selector_type must be client, tag, or group")

    plan = await services.qos_plans.create(
        controller=controller,
        site=site,
        selector_type=selector_type,
        selector_value=selector_value,
        download_kbps=download_kbps,
        upload_kbps=upload_kbps,
        client_keys=client_keys,
    )
    return {"available": True, **_capabilities(ctx, device), "plan": plan}


async def apply_client_qos_policy(
    ctx: Context, plan_token: str, confirm: bool = False
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return {
            "available": False,
            "reason": "QoS policy apply requires UNIFI_RUNTIME_ENABLED=true",
        }
    if not confirm:
        return {
            "available": True,
            "success": False,
            "confirmed": False,
            "message": "Applying a QoS policy requires confirm=true.",
        }
    plan = await services.qos_plans.get_for_apply(plan_token)
    return {
        "available": True,
        "success": False,
        **_capabilities(ctx, str(plan["controller"])),
        "mutation_attempted": False,
        "plan": plan,
    }
