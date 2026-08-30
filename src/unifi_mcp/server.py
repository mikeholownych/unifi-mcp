"""UniFi MCP Server - Main entry point."""

import logging
import sys
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_mcp.auth.authorization import ScopeAuthorizer, ScopeMiddleware
from unifi_mcp.clients.base import create_app_lifespan
from unifi_mcp.config import settings
from unifi_mcp.plugins import PluginManager, activate_plugins, discover_plugins
from unifi_mcp.tools import client_organization as organization_tools
from unifi_mcp.tools import exports as export_tools
from unifi_mcp.tools import observability as observability_tools
from unifi_mcp.tools import qos as qos_tools
from unifi_mcp.tools import runtime as runtime_tools
from unifi_mcp.tools import system as system_tools
from unifi_mcp.tools.network import clients as client_tools
from unifi_mcp.tools.network import devices as device_tools
from unifi_mcp.tools.network import insights as insight_tools
from unifi_mcp.tools.network import multisite as multisite_tools
from unifi_mcp.tools.network import sites as site_tools
from unifi_mcp.tools.network import stats as stat_tools
from unifi_mcp.tools.protect import cameras as protect_tools
from unifi_mcp.version import get_version

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _build_server_security(configured=settings) -> tuple[dict[str, Any], ScopeAuthorizer | None]:
    if configured.transport == "stdio":
        return {}, None
    from mcp.server.auth.settings import AuthSettings

    from unifi_mcp.auth.oidc import OIDCTokenVerifier

    authorizer = ScopeAuthorizer(
        configured.oidc_read_scope,
        configured.oidc_write_scope,
        configured.oidc_admin_scope,
    )
    verifier = OIDCTokenVerifier(
        issuer=configured.oidc_issuer or "",
        audience=configured.oidc_audience or "",
        algorithms=configured.oidc_allowed_algorithms,
        required_scope=configured.oidc_read_scope,
        cache_ttl_seconds=configured.oidc_cache_ttl_seconds,
        timeout_seconds=configured.oidc_timeout_seconds,
    )
    auth = AuthSettings(
        issuer_url=configured.oidc_issuer,
        resource_server_url=configured.http_public_url,
        required_scopes=[configured.oidc_read_scope],
    )
    return {
        "token_verifier": verifier,
        "auth": auth,
        "middleware": [ScopeMiddleware(authorizer)],
    }, authorizer


_security_options, scope_authorizer = _build_server_security()

# Create the MCP server with lifespan management
mcp = MCPServer(
    name="UniFi MCP Server",
    version=get_version(),
    instructions="""
    Manage and analyze UniFi network and Protect infrastructure.

    This server provides tools for:
    - Device management (APs, switches, routers)
    - Client management (connected devices)
    - Site and network configuration
    - Network statistics and monitoring
    - AI-powered network analysis and troubleshooting
    - UniFi Protect camera management and snapshots
    - Multi-site orchestration (global inventory, health, client summary)

    Supports multiple UniFi devices. Use list_unifi_devices to see configured devices.
    Use the 'device' parameter to target specific devices when you have multiple.
    Use get_global_health / get_global_inventory for cross-device aggregation.

    Use the insight tools (analyze_network_issues, get_optimization_recommendations, etc.)
    for comprehensive network analysis and recommendations.
    """,
    lifespan=create_app_lifespan,
    **_security_options,
)

# =============================================================================
# System Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_server_health(ctx: Context) -> system_tools.ServerHealth:
    """Return redaction-safe UniFi MCP runtime health and service counts.

    Read-only operation. Reports counts of registered tools, configured data
    sources, and plugin status without exposing any secrets. Use to confirm the
    server and its sources are healthy before issuing deeper queries.
    """
    return await system_tools.build_server_health(ctx.request_context.lifespan_context)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_plugin_status():
    """List redacted trusted-plugin loading outcomes.

    Read-only operation. Returns whether trusted code and sandboxing are active
    plus each plugin's load outcome. Requires admin scope when called over HTTP.
    Use to audit which plugins loaded successfully after startup.
    """
    return {
        "trusted_code": True,
        "sandboxed": False,
        "plugins": plugin_manager.status(),
    }


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_snapshot_capabilities(ctx: Context):
    """Describe portable snapshot and report capabilities plus native backup limits.

    Read-only operation. Returns supported report formats (html, csv), whether
    native controller backup/restore are available, and the configured source
    list. Use to learn what export_portable_snapshot and export_network_report
    can produce before calling them.
    """
    return await export_tools.get_snapshot_capabilities(ctx)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def export_portable_snapshot(
    ctx: Context,
    filename: Annotated[
        Annotated[
            str,
            Field(
                description="Target file name written inside the confined export directory (no path traversal)."
            ),
        ],
        Field(
            description="Target file name written inside the confined export directory (no path traversal)."
        ),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Safety confirmation. Must be True to actually write; otherwise returns a rejection message."
            ),
        ],
        Field(
            description="Safety confirmation. Must be True to actually write; otherwise returns a rejection message."
        ),
    ] = False,
):
    """Export a deterministic secret-free JSON snapshot to a local confined file.

    Mutating operation: writes a local file immediately, persisted in the export
    directory. Returns the filename, size, schema version, and a content SHA-256
    checksum for later verification with verify_snapshot. The call is rejected
    without writing unless confirm=true. Use export_network_report for
    human-readable HTML/CSV instead of the raw JSON model.

    Args:
        filename: Target file name written inside the confined export directory (no path traversal).
        confirm: Safety confirmation. Must be True to actually write; otherwise returns a rejection message.
    """
    return await export_tools.export_portable_snapshot(ctx, filename, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def verify_snapshot(
    ctx: Context,
    filename: Annotated[
        Annotated[
            str,
            Field(
                description="Name of the snapshot file (within the confined export directory) to validate."
            ),
        ],
        Field(
            description="Name of the snapshot file (within the confined export directory) to validate."
        ),
    ],
):
    """Verify the schema and checksum of a confined snapshot export.

    Read-only operation. Reads the named snapshot from the export directory and
    validates its schema, redaction status, and content SHA-256. Returns validity
    plus schema version and checksum for integrity checks. Use after
    export_portable_snapshot to confirm the file is intact and secret-free.

    Args:
        filename: Name of the snapshot file (within the confined export directory) to validate.
    """
    return await export_tools.verify_snapshot(ctx, filename)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def export_network_report(
    ctx: Context,
    filename: Annotated[
        Annotated[
            str,
            Field(
                description="Output report file name inside the confined export directory; must end with the chosen format extension (e.g. .html, .csv)."
            ),
        ],
        Field(
            description="Output report file name inside the confined export directory; must end with the chosen format extension (e.g. .html, .csv)."
        ),
    ],
    format: Annotated[
        Annotated[
            str,
            Field(
                description='Report renderer to use — "html" or "csv" (plugins may register additional formats).'
            ),
        ],
        Field(
            description='Report renderer to use — "html" or "csv" (plugins may register additional formats).'
        ),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Safety confirmation. Must be True to actually write; otherwise returns a rejection message."
            ),
        ],
        Field(
            description="Safety confirmation. Must be True to actually write; otherwise returns a rejection message."
        ),
    ] = False,
):
    """Export an HTML or CSV report rendered from the portable snapshot model.

    Mutating operation: writes a local report file immediately, persisted in the
    export directory. The call is rejected without writing unless confirm=true.
    Format must be "html" or "csv" and filename must end with the matching
    extension; plugins may register additional formats. Prefer
    export_portable_snapshot for the raw machine-readable model.

    Args:
        filename: Output report file name inside the confined export directory; must end with the chosen format extension (e.g. .html, .csv).
        format: Report renderer to use — "html" or "csv" (plugins may register additional formats).
        confirm: Safety confirmation. Must be True to actually write; otherwise returns a rejection message.
    """
    return await export_tools.export_network_report(ctx, filename, format, confirm)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def capture_observations_now(ctx: Context):
    """Capture a bounded batch of aggregate UniFi health observations immediately.

    Mutating operation: collects current health observations and persists them
    into the observation store right away, then refreshes cached metrics. Returns
    the number of inserted observations and any scope limitations. Use before
    query_observation_trends to ensure recent data, or rely on scheduled capture
    otherwise.
    """
    return await observability_tools.capture_observations_now(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def query_observation_trends(
    ctx: Context,
    kind: Annotated[
        Annotated[
            str,
            Field(description='Observation category to query (e.g. "health", "client", "device").'),
        ],
        Field(description='Observation category to query (e.g. "health", "client", "device").'),
    ],
    metric: Annotated[
        Annotated[
            str, Field(description='Metric name within the kind (e.g. "latency_ms", "cpu_pct").')
        ],
        Field(description='Metric name within the kind (e.g. "latency_ms", "cpu_pct").'),
    ],
    start: Annotated[
        Annotated[str, Field(description="Inclusive UTC start timestamp (ISO-8601).")],
        Field(description="Inclusive UTC start timestamp (ISO-8601)."),
    ],
    end: Annotated[
        Annotated[str, Field(description="Inclusive UTC end timestamp (ISO-8601).")],
        Field(description="Inclusive UTC end timestamp (ISO-8601)."),
    ],
    bucket_seconds: Annotated[
        Annotated[
            int, Field(description="Width of each trend bucket in seconds. Defaults to 300.")
        ],
        Field(description="Width of each trend bucket in seconds. Defaults to 300."),
    ] = 300,
    source: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional source filter (e.g. controller type); omit for all sources."
            ),
        ],
        Field(description="Optional source filter (e.g. controller type); omit for all sources."),
    ] = None,
    controller: Annotated[
        Annotated[
            str | None,
            Field(description="Optional controller identifier filter; omit for all controllers."),
        ],
        Field(description="Optional controller identifier filter; omit for all controllers."),
    ] = None,
    site: Annotated[
        Annotated[
            str | None,
            Field(description='Optional site name filter (e.g. "default"); omit for all sites.'),
        ],
        Field(description='Optional site name filter (e.g. "default"); omit for all sites.'),
    ] = None,
):
    """Query bounded UTC trend buckets for an observation kind and metric.

    Read-only operation. Returns evenly spaced time buckets between start and end
    with explicit gaps for missing intervals, so callers can distinguish absence
    from zero. Bucket size defaults to 300 seconds. Use capture_observations_now
    first if recent data is missing.

    Args:
        kind: Observation category to query (e.g. "health", "client", "device").
        metric: Metric name within the kind (e.g. "latency_ms", "cpu_pct").
        start: Inclusive UTC start timestamp (ISO-8601).
        end: Inclusive UTC end timestamp (ISO-8601).
        bucket_seconds: Width of each trend bucket in seconds. Defaults to 300.
        source: Optional source filter (e.g. controller type); omit for all sources.
        controller: Optional controller identifier filter; omit for all controllers.
        site: Optional site name filter (e.g. "default"); omit for all sites.
    """
    return await observability_tools.query_observation_trends(
        ctx, kind, metric, start, end, bucket_seconds, source, controller, site
    )


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_observation_scopes(ctx: Context):
    """List the aggregate observation scopes currently retained.

    Read-only operation. Returns the distinct scope dimensions (source,
    controller, site) present in the observation store. Use to discover valid
    filter values for query_observation_trends.
    """
    return await observability_tools.list_observation_scopes(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_observation_retention_status(ctx: Context):
    """Get aggregate observation count and retained time range.

    Read-only operation. Returns how many observations are stored and the
    earliest-to-latest retained time span. Use to gauge whether
    query_observation_trends can cover a desired window.
    """
    return await observability_tools.get_observation_retention_status(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_organization(
    ctx: Context,
    identity: Annotated[
        Annotated[
            str,
            Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
        ],
        Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Get durable local tags and group membership for one known client.

    Read-only operation: resolves the client by identity, then returns its
    persisted local organization record (tags and group membership). This
    data is local to the server (local_only) and does not mutate the controller.
    Use set_client_tags or assign_client_group to change it.

    Args:
        identity: Client MAC, IP, hostname, or alias to resolve to a known client.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await organization_tools.get_client_organization(ctx, identity, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_client_tags(
    ctx: Context,
    identity: Annotated[
        Annotated[
            str,
            Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
        ],
        Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
    ],
    tags: Annotated[
        Annotated[
            list[str],
            Field(description="Full replacement tag list; an empty list clears all tags."),
        ],
        Field(description="Full replacement tag list; an empty list clears all tags."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to apply the change; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to apply the change; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Replace local client tags by stable identity. Requires confirm=true.

    Mutating operation: overwrites the client's persisted local tags with the
    supplied list and is stored on the server (local_only), not the controller.
    Returns success=false unless confirm=true. Use get_client_organization to
    read current tags first; use assign_client_group for group membership.

    Args:
        identity: Client MAC, IP, hostname, or alias to resolve to a known client.
        tags: Full replacement tag list; an empty list clears all tags.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
        confirm: Must be True to apply the change; without it the call is a no-op.
            Defaults to False.
    """
    return await organization_tools.set_client_tags(ctx, identity, tags, site, device, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_client_group(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Unique group name to create.")],
        Field(description="Unique group name to create."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to create the group; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to create the group; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Create a controller-independent local client group. Requires confirm=true.

    Mutating operation: persists a new empty local group (local_only) scoped to
    the controller/site; it does not create anything on the UniFi controller.
    Returns success=false unless confirm=true. Use assign_client_group to add
    members, or list_client_groups to see existing groups.

    Args:
        name: Unique group name to create.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
        confirm: Must be True to create the group; without it the call is a no-op.
            Defaults to False.
    """
    return await organization_tools.create_client_group(ctx, name, site, device, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_client_group(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Name of the local group to delete.")],
        Field(description="Name of the local group to delete."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to delete the group; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to delete the group; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Delete a local group and its memberships. Requires confirm=true.

    Mutating operation: removes the local group (local_only) and detaches its
    members; it does not touch the UniFi controller. Returns success=false unless
    confirm=true. Recreate with create_client_group if needed.

    Args:
        name: Name of the local group to delete.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
        confirm: Must be True to delete the group; without it the call is a no-op.
            Defaults to False.
    """
    return await organization_tools.delete_client_group(ctx, name, site, device, confirm)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def assign_client_group(
    ctx: Context,
    identity: Annotated[
        Annotated[
            str,
            Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
        ],
        Field(description="Client MAC, IP, hostname, or alias to resolve to a known client."),
    ],
    group: Annotated[
        Annotated[
            str | None,
            Field(description="Group name to assign, or null/None to unassign the current group."),
        ],
        Field(description="Group name to assign, or null/None to unassign the current group."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to change membership; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to change membership; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Assign or unassign one local client group. Requires confirm=true.

    Mutating operation: sets the client's single local group membership (local_only)
    to the given group, or clears it when group is null. Does not mutate the
    controller. Returns success=false unless confirm=true. Use set_client_tags for
    tags, or list_clients_by_organization to find clients in a group.

    Args:
        identity: Client MAC, IP, hostname, or alias to resolve to a known client.
        group: Group name to assign, or null/None to unassign the current group.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
        confirm: Must be True to change membership; without it the call is a no-op.
            Defaults to False.
    """
    return await organization_tools.assign_client_group(ctx, identity, group, site, device, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_client_groups(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List local client groups and deterministic member counts.

    Read-only operation: returns the local groups (local_only) for the
    controller/site with a deterministic member count per group. Use
    list_clients_by_organization to enumerate the actual member identities.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await organization_tools.list_client_groups(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_clients_by_organization(
    ctx: Context,
    tag: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional local tag to filter clients by; mutually exclusive with group."
            ),
        ],
        Field(
            description="Optional local tag to filter clients by; mutually exclusive with group."
        ),
    ] = None,
    group: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional local group name to filter clients by; mutually exclusive with tag."
            ),
        ],
        Field(
            description="Optional local group name to filter clients by; mutually exclusive with tag."
        ),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List stable client identities for exactly one local tag or group.

    Read-only operation: returns the persisted client keys (MACs) that match a
    single tag or group filter (local_only). Exactly one of tag or group must be
    supplied; supplying neither or both is an error. Use list_client_groups to
    discover group names.

    Args:
        tag: Optional local tag to filter clients by; mutually exclusive with group.
        group: Optional local group name to filter clients by; mutually exclusive
            with tag.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await organization_tools.list_clients_by_organization(ctx, tag, group, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_qos_capabilities(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Describe validated controller QoS mutation capabilities.

    Read-only operation: reports whether a validated controller QoS adapter is
    available for the targeted device. Previews created by plan_client_qos_policy
    are always local; apply_client_qos_policy performs no controller mutation in
    the current release. Use this before planning a policy to set expectations.

    Args:
        device: Optional device name to target a specific console; omit for default.
    """
    return await qos_tools.get_client_qos_capabilities(ctx, device)


@mcp.tool()
async def plan_client_qos_policy(
    ctx: Context,
    selector_type: Annotated[
        Annotated[str, Field(description='Scope of the policy - "client", "tag", or "group".')],
        Field(description='Scope of the policy - "client", "tag", or "group".'),
    ],
    selector_value: Annotated[
        Annotated[
            str,
            Field(
                description='Client identity (MAC/IP/hostname) when selector_type is "client", otherwise the tag or group name to expand to clients.'
            ),
        ],
        Field(
            description='Client identity (MAC/IP/hostname) when selector_type is "client", otherwise the tag or group name to expand to clients.'
        ),
    ],
    download_kbps: Annotated[
        Annotated[int, Field(description="Maximum download bandwidth in kilobits per second.")],
        Field(description="Maximum download bandwidth in kilobits per second."),
    ],
    upload_kbps: Annotated[
        Annotated[int, Field(description="Maximum upload bandwidth in kilobits per second.")],
        Field(description="Maximum upload bandwidth in kilobits per second."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Persist a deterministic QoS target preview without controller mutation.

    Mutating (local) operation: resolves selector_type/selector_value to concrete
    client keys and stores a durable QoS plan (plan_token) on the server with the
    requested download/upload limits. It does NOT change the controller. Pair the
    returned plan_token with apply_client_qos_policy to attempt activation. Requires
    UNIFI_RUNTIME_ENABLED=true; use get_client_qos_capabilities to check adapters.

    Args:
        selector_type: Scope of the policy - "client", "tag", or "group".
        selector_value: Client identity (MAC/IP/hostname) when selector_type is
            "client", otherwise the tag or group name to expand to clients.
        download_kbps: Maximum download bandwidth in kilobits per second.
        upload_kbps: Maximum upload bandwidth in kilobits per second.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await qos_tools.plan_client_qos_policy(
        ctx,
        selector_type,
        selector_value,
        download_kbps,
        upload_kbps,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def apply_client_qos_policy(
    ctx: Context,
    plan_token: Annotated[
        Annotated[
            str, Field(description="Token returned by plan_client_qos_policy identifying the plan.")
        ],
        Field(description="Token returned by plan_client_qos_policy identifying the plan."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to attempt application; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to attempt application; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Apply a validated QoS preview when a supported adapter exists. Requires confirmation.

    Mutating operation: loads the plan referenced by plan_token and attempts to
    activate it. In the current release no validated adapter exists, so no controller
    mutation is performed (mutation_attempted=false); the call records the attempt.
    Returns success=false unless confirm=true. Use plan_client_qos_policy first to
    obtain a plan_token.

    Args:
        plan_token: Token returned by plan_client_qos_policy identifying the plan.
        confirm: Must be True to attempt application; without it the call is a no-op.
            Defaults to False.
    """
    return await qos_tools.apply_client_qos_policy(ctx, plan_token, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_runtime_events(
    ctx: Context,
    limit: Annotated[
        Annotated[int, Field(description="Maximum number of events to return. Defaults to 100.")],
        Field(description="Maximum number of events to return. Defaults to 100."),
    ] = 100,
):
    """List normalized events retained by the optional runtime store.

    Read-only operation: returns up to `limit` normalized events persisted by the
    runtime store. Requires UNIFI_RUNTIME_ENABLED=true; otherwise unavailable. Use
    get_event_polling_status to see which sources feed events.

    Args:
        limit: Maximum number of events to return. Defaults to 100.
    """
    return await runtime_tools.list_runtime_events(ctx, limit)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_event_polling_status(ctx: Context):
    """List event source capabilities and background polling state.

    Read-only operation: returns each known event source with its capabilities and
    whether background polling is enabled. Use this to discover source names for
    poll_events_now, or list_runtime_events to read stored events.
    """
    return await runtime_tools.get_event_polling_status(ctx)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def poll_events_now(
    ctx: Context,
    source: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional source name to poll a single source; omit for all sources."
            ),
        ],
        Field(description="Optional source name to poll a single source; omit for all sources."),
    ] = None,
    device_name: Annotated[
        Annotated[
            str | None,
            Field(description="Optional console/device name to filter sources; omit for all."),
        ],
        Field(description="Optional console/device name to filter sources; omit for all."),
    ] = None,
):
    """Poll supported event sources now and durably deduplicate results.

    Mutating (local) operation: triggers an immediate poll of matching event
    sources, inserts new normalized events into the runtime store, and
    deduplicates against what is already persisted. Requires UNIFI_RUNTIME_ENABLED=true.
    Use get_event_polling_status to discover source names; use list_runtime_events
    to read stored results.

    Args:
        source: Optional source name to poll a single source; omit for all sources.
        device_name: Optional console/device name to filter sources; omit for all.
    """
    return await runtime_tools.poll_events_now(ctx, source, device_name)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_schedules(ctx: Context):
    """List allowlisted interval schedules.

    Read-only operation: returns the persisted interval schedules (name, job,
    interval, enabled) and whether background automation is enabled. Use
    create_interval_schedule to add one, or run_schedule_now to trigger it.
    """
    return await runtime_tools.list_schedules(ctx)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_interval_schedule(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Unique schedule identifier.")],
        Field(description="Unique schedule identifier."),
    ],
    job_name: Annotated[
        Annotated[str, Field(description="Allowlisted job to run on the interval.")],
        Field(description="Allowlisted job to run on the interval."),
    ],
    interval_seconds: Annotated[
        Annotated[int, Field(description="Recurrence period between runs, in seconds.")],
        Field(description="Recurrence period between runs, in seconds."),
    ],
    arguments: Annotated[
        Annotated[
            dict[str, Any] | None,
            Field(description="Optional keyword arguments passed to the job on each run."),
        ],
        Field(description="Optional keyword arguments passed to the job on each run."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to create the schedule; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to create the schedule; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Create an allowlisted recurring job. Requires confirm=true.

    Mutating operation: persists a new interval schedule that runs job_name with
    the given arguments every interval_seconds. Returns success=false unless
    confirm=true. The job must be on the allowlist. Use set_schedule_enabled to
    pause it, or delete_schedule to remove it.

    Args:
        name: Unique schedule identifier.
        job_name: Allowlisted job to run on the interval.
        interval_seconds: Recurrence period between runs, in seconds.
        arguments: Optional keyword arguments passed to the job on each run.
        confirm: Must be True to create the schedule; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.create_interval_schedule(
        ctx, name, job_name, interval_seconds, arguments, confirm
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_schedule_enabled(
    ctx: Context,
    schedule_id: Annotated[
        Annotated[str, Field(description="Identifier of the schedule to modify.")],
        Field(description="Identifier of the schedule to modify."),
    ],
    enabled: Annotated[
        Annotated[
            bool, Field(description="True to enable (run on interval) or False to pause it.")
        ],
        Field(description="True to enable (run on interval) or False to pause it."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to change the schedule; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to change the schedule; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Enable or pause a schedule. Requires confirm=true.

    Mutating operation: flips the enabled flag on the identified schedule and
    persists it. Returns success=false unless confirm=true. Use
    create_interval_schedule to add, or delete_schedule to remove.

    Args:
        schedule_id: Identifier of the schedule to modify.
        enabled: True to enable (run on interval) or False to pause it.
        confirm: Must be True to change the schedule; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.set_schedule_enabled(ctx, schedule_id, enabled, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_schedule(
    ctx: Context,
    schedule_id: Annotated[
        Annotated[str, Field(description="Identifier of the schedule to delete.")],
        Field(description="Identifier of the schedule to delete."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to delete the schedule; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to delete the schedule; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Delete a non-running schedule. Requires confirm=true.

    Mutating operation: removes the identified schedule from the store. Returns
    success=false unless confirm=true. Use create_interval_schedule to add one, or
    set_schedule_enabled to pause instead of delete.

    Args:
        schedule_id: Identifier of the schedule to delete.
        confirm: Must be True to delete the schedule; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.delete_schedule(ctx, schedule_id, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def run_schedule_now(
    ctx: Context,
    schedule_id: Annotated[
        Annotated[str, Field(description="Identifier of the schedule to run immediately.")],
        Field(description="Identifier of the schedule to run immediately."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to run the schedule; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to run the schedule; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Run one allowlisted schedule immediately. Requires confirm=true.

    Mutating operation: executes the identified schedule's job once, outside its
    normal interval, and records the run. Returns success=false unless confirm=true.
    Use list_job_runs to inspect the outcome; use set_schedule_enabled to disable
    auto-runs.

    Args:
        schedule_id: Identifier of the schedule to run immediately.
        confirm: Must be True to run the schedule; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.run_schedule_now(ctx, schedule_id, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_job_runs(
    ctx: Context,
    limit: Annotated[
        Annotated[int, Field(description="Maximum number of job runs to return. Defaults to 100.")],
        Field(description="Maximum number of job runs to return. Defaults to 100."),
    ] = 100,
):
    """List redacted background job run outcomes.

    Read-only operation: returns up to `limit` recent schedule/job run records
    (status, timestamps) with secret values redacted. Use run_schedule_now or
    list_schedules to discover runnable schedules.

    Args:
        limit: Maximum number of job runs to return. Defaults to 100.
    """
    return await runtime_tools.list_job_runs(ctx, limit)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_webhook_destinations(ctx: Context):
    """List webhook destinations without secret values.

    Read-only operation: returns configured outbound webhook destinations with
    secret material omitted. Use create_webhook_destination to add one, or
    list_webhook_deliveries to see send history.
    """
    return await runtime_tools.list_webhook_destinations(ctx)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_webhook_destination(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Unique destination identifier.")],
        Field(description="Unique destination identifier."),
    ],
    url: Annotated[
        Annotated[str, Field(description="Endpoint that receives webhook payloads.")],
        Field(description="Endpoint that receives webhook payloads."),
    ],
    secret_env_name: Annotated[
        Annotated[
            str | None, Field(description="Optional name of an env var holding the signing secret.")
        ],
        Field(description="Optional name of an env var holding the signing secret."),
    ] = None,
    categories: Annotated[
        Annotated[
            list[str] | None,
            Field(description="Optional list of event categories to send; empty sends all."),
        ],
        Field(description="Optional list of event categories to send; empty sends all."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to create the destination; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to create the destination; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Create a filtered outbound webhook. Requires confirm=true.

    Mutating operation: persists a new outbound webhook destination posting to url,
    optionally signing with a secret from secret_env_name and limited to categories.
    Returns success=false unless confirm=true. Use set_webhook_destination_enabled to
    pause it, or delete_webhook_destination to remove it.

    Args:
        name: Unique destination identifier.
        url: Endpoint that receives webhook payloads.
        secret_env_name: Optional name of an env var holding the signing secret.
        categories: Optional list of event categories to send; empty sends all.
        confirm: Must be True to create the destination; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.create_webhook_destination(
        ctx, name, url, secret_env_name, categories, confirm
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_webhook_destination_enabled(
    ctx: Context,
    destination_id: Annotated[
        Annotated[str, Field(description="Identifier of the webhook destination to modify.")],
        Field(description="Identifier of the webhook destination to modify."),
    ],
    enabled: Annotated[
        Annotated[bool, Field(description="True to enable delivery or False to pause it.")],
        Field(description="True to enable delivery or False to pause it."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to change the destination; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to change the destination; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Enable or pause a webhook destination. Requires confirm=true.

    Mutating operation: flips the enabled flag on the identified webhook destination
    and persists it. Returns success=false unless confirm=true. Use
    create_webhook_destination to add, or delete_webhook_destination to remove.

    Args:
        destination_id: Identifier of the webhook destination to modify.
        enabled: True to enable delivery or False to pause it.
        confirm: Must be True to change the destination; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.set_webhook_destination_enabled(
        ctx, destination_id, enabled, confirm
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_webhook_destination(
    ctx: Context,
    destination_id: Annotated[
        Annotated[str, Field(description="Identifier of the webhook destination to delete.")],
        Field(description="Identifier of the webhook destination to delete."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to delete the destination; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to delete the destination; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Delete a webhook destination and queued deliveries. Requires confirm=true.

    Mutating operation: removes the identified webhook destination and its queued
    deliveries from the store. Returns success=false unless confirm=true. Use
    create_webhook_destination to add one.

    Args:
        destination_id: Identifier of the webhook destination to delete.
        confirm: Must be True to delete the destination; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.delete_webhook_destination(ctx, destination_id, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def test_webhook_destination(
    ctx: Context,
    destination_id: Annotated[
        Annotated[str, Field(description="Identifier of the webhook destination to test.")],
        Field(description="Identifier of the webhook destination to test."),
    ],
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Must be True to send the test payload; without it the call is a no-op. Defaults to False."
            ),
        ],
        Field(
            description="Must be True to send the test payload; without it the call is a no-op. Defaults to False."
        ),
    ] = False,
):
    """Send a synthetic payload to a webhook destination. Requires confirm=true.

    Mutating (external) operation: dispatches a synthetic test payload to the
    identified destination and records the delivery outcome. Returns success=false
    unless confirm=true. Use list_webhook_deliveries to inspect the result.

    Args:
        destination_id: Identifier of the webhook destination to test.
        confirm: Must be True to send the test payload; without it the call is a no-op.
            Defaults to False.
    """
    return await runtime_tools.test_webhook_destination(ctx, destination_id, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_webhook_deliveries(
    ctx: Context,
    limit: Annotated[
        Annotated[
            int, Field(description="Maximum number of delivery records to return. Defaults to 100.")
        ],
        Field(description="Maximum number of delivery records to return. Defaults to 100."),
    ] = 100,
):
    """List redacted webhook delivery and dead-letter state.

    Read-only operation: returns up to `limit` delivery records (status, attempts,
    dead-letter state) with secret values redacted. Use test_webhook_destination to
    trigger a send, or list_webhook_destinations to see configured endpoints.

    Args:
        limit: Maximum number of delivery records to return. Defaults to 100.
    """
    return await runtime_tools.list_webhook_deliveries(ctx, limit)


# =============================================================================
# Device Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_devices(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List all UniFi network devices (APs, switches, routers) on a site.

    Read-only operation: returns a per-device summary for the targeted site,
    including name, MAC, model, type, IP, online state, uptime, and firmware
    version. Use this to discover the MAC values needed by get_device_details,
    restart_device, and the other device tools.

    Distinction: use list_unifi_devices to see the server's configured consoles
    (controller roster); use get_global_inventory for an aggregated inventory
    across all consoles. This tool lists devices *within* one site on one console.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.list_devices(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_details(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Get detailed configuration and runtime record for one UniFi device.

    Read-only operation: returns the device's ports, radios, uplink, system
    stats, temperatures, and traffic counters. The device is resolved by MAC
    first, then by name. Use list_devices to find the MAC; use get_device_stats
    for a metrics-only view without the full config dump.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.get_device_details(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def restart_device(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Restart (reboot) a UniFi device by MAC address.

    Mutating operation: sends a reboot command that is persisted on the
    console; the device goes offline briefly and reconnects. Unlike
    provision_device (re-push config without reboot) and upgrade_device
    (firmware update), this power-cycles the device. No other config change is
    needed.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.restart_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def locate_device(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    enabled: Annotated[
        Annotated[
            bool, Field(description="True to start LED blinking, False to stop. Defaults to True.")
        ],
        Field(description="True to start LED blinking, False to stop. Defaults to True."),
    ] = True,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Enable or disable LED blinking to physically locate a device.

    Mutating operation: toggles the locator LED on the device and is persisted
    on the console. Set enabled=True to start blinking, False to stop. This
    changes only the LED state and has no effect on connectivity or config.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        enabled: True to start LED blinking, False to stop. Defaults to True.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.locate_device(ctx, mac, enabled, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_stats(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Get performance and traffic statistics for one UniFi device.

    Read-only operation: returns CPU/memory load, temperatures, fan level,
    client counts (user/guest), traffic totals, and AP radio stats where
    applicable. Use get_device_details for the full config record instead of
    metrics, or list_devices for a lightweight summary.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.get_device_stats(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def upgrade_device(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Upgrade a device's firmware to the latest available version.

    Mutating operation: initiates a firmware upgrade that is persisted once
    applied; the device reboots during the update. Unlike restart_device (plain
    reboot) and provision_device (config re-push), this changes the running
    firmware. Only proceeds when an upgrade is available on the console.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.upgrade_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def provision_device(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Force re-provision a device with its current configuration.

    Mutating operation: re-pushes the existing config to the device and is
    persisted on the console, without changing firmware or power-cycling like
    upgrade_device or restart_device. Use after config edits to force the
    device to re-adopt current settings.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.provision_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_ports(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List the switch/gateway ports on a device with link and VLAN details.

    Read-only operation: returns each port's index, name, media (GE/SFP), link
    state, speed, native network (VLAN) ID, PoE mode, forward setting, and the
    last connected peer MAC/IP where known. Use this to find the port_idx and
    current values before calling set_device_port.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await device_tools.get_device_ports(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def set_device_port(
    ctx: Context,
    mac: Annotated[
        Annotated[
            str,
            Field(
                description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
            ),
        ],
        Field(
            description="Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or aabbccddeeff)."
        ),
    ],
    port_idx: Annotated[
        Annotated[
            int, Field(description="Port number to configure (1-based; e.g. 1-24 or SFP 25/26).")
        ],
        Field(description="Port number to configure (1-based; e.g. 1-24 or SFP 25/26)."),
    ],
    name: Annotated[
        Annotated[str | None, Field(description='Optional custom port name (e.g. "Cameras").')],
        Field(description='Optional custom port name (e.g. "Cameras").'),
    ] = None,
    native_network: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional network or VLAN name (or its ID) to set as the port's native/untagged VLAN."
            ),
        ],
        Field(
            description="Optional network or VLAN name (or its ID) to set as the port's native/untagged VLAN."
        ),
    ] = None,
    poe_mode: Annotated[
        Annotated[
            str | None, Field(description='Optional PoE mode - "auto", "on", "off", or "passv24".')
        ],
        Field(description='Optional PoE mode - "auto", "on", "off", or "passv24".'),
    ] = None,
    forward: Annotated[
        Annotated[
            str | None,
            Field(description='Optional VLAN forwarding - "all" (every VLAN) or "customize".'),
        ],
        Field(description='Optional VLAN forwarding - "all" (every VLAN) or "customize".'),
    ] = None,
    enabled: Annotated[
        Annotated[
            bool | None,
            Field(description="Optional port enable state; True connects, False disables."),
        ],
        Field(description="Optional port enable state; True connects, False disables."),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool, Field(description="Must be True to apply the port change. Defaults to False.")
        ],
        Field(description="Must be True to apply the port change. Defaults to False."),
    ] = False,
):
    """Configure a single switch port: native VLAN, PoE mode, name, or enable state.

    Mutating operation: applied immediately and persisted on the console,
    changing untagged VLAN traffic, PoE delivery, or link state on that port.
    Only the fields you provide change. Requires confirm=true because a port
    change can disrupt connectivity for the attached device or downstream
    network. Use get_device_ports first to find the port_idx and current values.

    Args:
        mac: Device MAC address (case-insensitive; aa:bb:cc:dd:ee:ff or
            aabbccddeeff).
        port_idx: Port number to configure (1-based; e.g. 1-24 or SFP 25/26).
        name: Optional custom port name (e.g. "Cameras").
        native_network: Optional network or VLAN name (or its ID) to set as the
            port's native/untagged VLAN.
        poe_mode: Optional PoE mode - "auto", "on", "off", or "passv24".
        forward: Optional VLAN forwarding - "all" (every VLAN) or "customize".
        enabled: Optional port enable state; True connects, False disables.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
        confirm: Must be True to apply the port change. Defaults to False.
    """
    return await device_tools.set_device_port(
        ctx,
        mac,
        port_idx,
        name,
        native_network,
        poe_mode,
        forward,
        enabled,
        site,
        device,
        confirm,
    )


# =============================================================================
# Client Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_clients(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List all currently connected (online) clients on a site.

    Read-only operation: returns only clients with an active connection at query
    time. For the historical/known roster including offline clients use
    list_all_clients; for deep per-client detail use get_client_details.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.list_clients(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_all_clients(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """List every known client (connected and offline) on a site.

    Read-only operation: includes clients not currently connected, so it is the
    superset of list_clients. Use get_client_details for deep per-client detail or
    list_clients when you only need active connections.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.list_all_clients(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_details(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Get the full device record for one client by MAC address.

    Read-only operation: returns the client's identity, connection state, IP,
    signal/AP association, and history. Deeper than list_clients/list_all_clients,
    which return summarized rows only.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.get_client_details(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def block_client(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Block a client from accessing the network by MAC address.

    Mutating operation: the block is applied immediately and persists in the
    controller's firewall/blocklist. Use unblock_client to restore access, or
    kick_client to drop the connection without a persistent block.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.block_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def unblock_client(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Remove a prior block so a client can reconnect to the network.

    Mutating operation: clears the persistent block set by block_client. Use
    block_client to re-block, or kick_client for a non-persistent disconnect.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.unblock_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def kick_client(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Force-disconnect a client; it may reconnect normally.

    Mutating operation: drops the active session without a persistent block, so
    the client can re-associate. Use block_client/unblock_client for a lasting
    block, or forget_client to remove the client record entirely.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.kick_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def forget_client(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Remove a client from the controller's known-clients list.

    Destructive operation: deletes the client's stored identity and history; the
    client can still reappear on reconnect. Use kick_client to drop a session
    without deletion, or block_client to deny access persistently.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.forget_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_traffic(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="Client MAC address to target.")],
        Field(description="Client MAC address to target."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Get traffic statistics (rx/tx, throughput) for one client by MAC address.

    Read-only operation: returns the client's cumulative and recent traffic
    counters. Use get_client_details for identity/connection state, or
    get_traffic_summary for site-wide traffic rather than a single client.

    Args:
        mac: Client MAC address to target.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.get_client_traffic(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def reserve_client_ip(
    ctx: Context,
    client: Annotated[
        Annotated[str, Field(description="Client MAC address or name to reserve an IP for.")],
        Field(description="Client MAC address or name to reserve an IP for."),
    ],
    ip: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional IPv4 address to reserve; omit to keep the client's current IP."
            ),
        ],
        Field(
            description="Optional IPv4 address to reserve; omit to keep the client's current IP."
        ),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Create a DHCP reservation pinning an IP to a client.

    Mutating operation: reserves the client's current IP (when ip is omitted) or
    the given IPv4 address, so the client keeps it across leases. Requires the
    client to be known; use list_clients to find the current IP if needed.

    Args:
        client: Client MAC address or name to reserve an IP for.
        ip: Optional IPv4 address to reserve; omit to keep the client's current IP.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await client_tools.reserve_client_ip(ctx, client, ip, site, device)


# =============================================================================
# Site Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_sites(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for the default device."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for the default device."
        ),
    ] = None,
):
    """List all UniFi sites accessible to the current user.

    Read-only operation: returns each site's id and name from the targeted
    console(s). Use get_site_health / get_site_settings for per-site detail once
    you have a site name.

    Args:
        device: Optional console name to target a specific UniFi device; omit for
            the default device.
    """
    return await site_tools.list_sites(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_site_health(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get comprehensive health status for a site.

    Read-only operation: returns per-subsystem health (WAN/LAN/WLAN status, score,
    and device/user counts) for the named site. Use get_network_health for a lighter
    summary, or get_global_health across consoles.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_site_health(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_site_settings(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get the configuration settings for a site.

    Read-only operation: returns the site's settings record (network, wireless,
    and advanced options) as stored on the controller. Use get_sysinfo for controller
    identity rather than tunable settings.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_site_settings(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_site_settings(
    ctx: Context,
    settings: Annotated[
        dict[str, Any],
        Field(
            description="Dictionary of settings to update (e.g., {'auto_backup_enabled': true})."
        ),
    ],
    site: Annotated[
        str, Field(description='Site to operate on. Defaults to "default".')
    ] = "default",
    device: Annotated[
        str | None,
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Update site settings.

    Mutating operation: changes are applied immediately and persisted.
    Settings are key-value pairs matching the UniFi site setting schema.
    Use get_site_settings first to see available settings and their current values.

    Args:
        settings: Dictionary of settings to update (e.g., {"auto_backup_enabled": true})
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for default.
    """
    return await site_tools.update_site_settings(ctx, settings, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_sysinfo(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get system information for the site controller.

    Read-only operation: returns controller identity, firmware version, and
    hardware/model details for the named site. Use get_site_settings for tunable
    settings instead of controller metadata.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_sysinfo(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_networks(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get all network/VLAN configurations for a site.

    Read-only operation: returns each network's name, purpose, VLAN id, subnet CIDR,
    and DHCP settings. Use create_network / update_network / delete_network to change
    them, or get_wlans for wireless networks.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_networks(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_network(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description='Network name (e.g. "IoT").')],
        Field(description='Network name (e.g. "IoT").'),
    ],
    subnet: Annotated[
        Annotated[
            str | None,
            Field(description='Subnet in CIDR form (e.g. "192.168.50.1/24"); omit for unrouted.'),
        ],
        Field(description='Subnet in CIDR form (e.g. "192.168.50.1/24"); omit for unrouted.'),
    ] = None,
    vlan: Annotated[
        Annotated[
            int | None,
            Field(description="VLAN id (1-4094) for a tagged segment; omit for untagged."),
        ],
        Field(description="VLAN id (1-4094) for a tagged segment; omit for untagged."),
    ] = None,
    purpose: Annotated[
        Annotated[
            str,
            Field(
                description='Segment type — "corporate", "guest", or "wan". Defaults to "corporate".'
            ),
        ],
        Field(
            description='Segment type — "corporate", "guest", or "wan". Defaults to "corporate".'
        ),
    ] = "corporate",
    domain_name: Annotated[
        Annotated[
            str | None,
            Field(description='DNS domain name advertised to clients (e.g. "example.local").'),
        ],
        Field(description='DNS domain name advertised to clients (e.g. "example.local").'),
    ] = None,
    dhcp_start: Annotated[
        Annotated[
            str | None,
            Field(description="DHCP pool start IP; supply with dhcp_stop to enable DHCP."),
        ],
        Field(description="DHCP pool start IP; supply with dhcp_stop to enable DHCP."),
    ] = None,
    dhcp_stop: Annotated[
        Annotated[
            str | None,
            Field(description="DHCP pool end IP; supply with dhcp_start to enable DHCP."),
        ],
        Field(description="DHCP pool end IP; supply with dhcp_start to enable DHCP."),
    ] = None,
    dhcp_lease_time: Annotated[
        Annotated[int | None, Field(description="DHCP lease duration in seconds (default 86400).")],
        Field(description="DHCP lease duration in seconds (default 86400)."),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to create. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to create. Defaults to False."),
    ] = False,
):
    """Create a new network/VLAN segment on the gateway (corporate by default).

    Mutating operation: applied immediately and persisted on the UniFi console.
    Provide subnet in CIDR form and an optional VLAN id to tag the segment; enable
    DHCP by supplying both dhcp_start and dhcp_stop. Requires confirm=true because
    routing/VLAN/DHCP changes can disrupt connectivity. Inspect with get_networks;
    reverse with delete_network.

    Args:
        name: Network name (e.g. "IoT").
        subnet: Subnet in CIDR form (e.g. "192.168.50.1/24"); omit for unrouted.
        vlan: VLAN id (1-4094) for a tagged segment; omit for untagged.
        purpose: Segment type — "corporate", "guest", or "wan". Defaults to "corporate".
        domain_name: DNS domain name advertised to clients (e.g. "example.local").
        dhcp_start: DHCP pool start IP; supply with dhcp_stop to enable DHCP.
        dhcp_stop: DHCP pool end IP; supply with dhcp_start to enable DHCP.
        dhcp_lease_time: DHCP lease duration in seconds (default 86400).
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
        confirm: Safety gate: must be True to create. Defaults to False.
    """
    return await site_tools.create_network(
        ctx,
        name,
        subnet,
        vlan,
        purpose,
        domain_name,
        dhcp_start,
        dhcp_stop,
        dhcp_lease_time,
        site,
        device,
        confirm,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_network(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Network name or record id to update.")],
        Field(description="Network name or record id to update."),
    ],
    name_new: Annotated[
        Annotated[str | None, Field(description="Rename the network to this value.")],
        Field(description="Rename the network to this value."),
    ] = None,
    subnet: Annotated[
        Annotated[
            str | None, Field(description='New subnet in CIDR form (e.g. "192.168.50.1/24").')
        ],
        Field(description='New subnet in CIDR form (e.g. "192.168.50.1/24").'),
    ] = None,
    vlan: Annotated[
        Annotated[
            int | None, Field(description="New VLAN id (1-4094); pass -1 to clear VLAN tagging.")
        ],
        Field(description="New VLAN id (1-4094); pass -1 to clear VLAN tagging."),
    ] = None,
    domain_name: Annotated[
        Annotated[str | None, Field(description="New DNS domain name for clients.")],
        Field(description="New DNS domain name for clients."),
    ] = None,
    dhcp_start: Annotated[
        Annotated[
            str | None,
            Field(description="New DHCP pool start IP; pair with dhcp_stop to enable DHCP."),
        ],
        Field(description="New DHCP pool start IP; pair with dhcp_stop to enable DHCP."),
    ] = None,
    dhcp_stop: Annotated[
        Annotated[
            str | None,
            Field(description="New DHCP pool end IP; pair with dhcp_start to enable DHCP."),
        ],
        Field(description="New DHCP pool end IP; pair with dhcp_start to enable DHCP."),
    ] = None,
    dhcp_lease_time: Annotated[
        Annotated[int | None, Field(description="New DHCP lease duration in seconds.")],
        Field(description="New DHCP lease duration in seconds."),
    ] = None,
    enabled: Annotated[
        Annotated[bool | None, Field(description="Enable or disable the network.")],
        Field(description="Enable or disable the network."),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to apply. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to apply. Defaults to False."),
    ] = False,
):
    """Update a network/VLAN; only the fields you provide change.

    Mutating operation: applied immediately and persisted on the UniFi console.
    A single field change preserves the network's other settings. Pass both empty
    dhcp_start and dhcp_stop to disable DHCP. Requires confirm=true because VLAN,
    routing, or enable-state changes can disconnect clients. Inspect with get_networks.

    Args:
        name: Network name or record id to update.
        name_new: Rename the network to this value.
        subnet: New subnet in CIDR form (e.g. "192.168.50.1/24").
        vlan: New VLAN id (1-4094); pass -1 to clear VLAN tagging.
        domain_name: New DNS domain name for clients.
        dhcp_start: New DHCP pool start IP; pair with dhcp_stop to enable DHCP.
        dhcp_stop: New DHCP pool end IP; pair with dhcp_start to enable DHCP.
        dhcp_lease_time: New DHCP lease duration in seconds.
        enabled: Enable or disable the network.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
        confirm: Safety gate: must be True to apply. Defaults to False.
    """
    return await site_tools.update_network(
        ctx,
        name,
        name_new,
        subnet,
        vlan,
        domain_name,
        dhcp_start,
        dhcp_stop,
        dhcp_lease_time,
        enabled,
        site,
        device,
        confirm,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_network(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Network name or record id to delete.")],
        Field(description="Network name or record id to delete."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to delete. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to delete. Defaults to False."),
    ] = False,
):
    """Delete a network/VLAN by name or ID.

    Mutating operation: removed immediately and persisted on the UniFi console.
    Requires confirm=true because deleting a network can drop clients and routes that
    depend on it. List networks with get_networks first to confirm the target.

    Args:
        name: Network name or record id to delete.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
        confirm: Safety gate: must be True to delete. Defaults to False.
    """
    return await site_tools.delete_network(ctx, name, site, device, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_wlans(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get all wireless network (SSID) configurations for a site.

    Read-only operation: returns each WLAN's name, id, enabled state, guest flag,
    and security settings. Use create_wlan / update_wlan / delete_wlan to change
    them, or get_networks for wired networks.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_wlans(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_port_profiles(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get switch port profile configurations for a site.

    Read-only operation: returns each port profile's name and the settings applied
    to member switch ports (PoE, VLAN, forwarding). Use set_device_port to apply
    changes to a specific physical port.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_port_profiles(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_firewall_rules(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get legacy firewall rule configurations for a site.

    Read-only operation: returns each rule's name, action, protocol, port, ruleset,
    and firewall-group bindings. Modern controllers use zone-based policies instead —
    see get_firewall_policies. Use create_firewall_policy for zone-based filtering.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_firewall_rules(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_firewall_policies(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get zone-based firewall policies (UniFi Network 9+).

    Read-only operation: returns each policy's name, action, protocol, index order,
    and source/destination zone ids. Policies are evaluated in index order; predefined
    "(Return)" companions appear alongside custom rules. Use create_firewall_policy to
    add one, or set_firewall_policy_enabled / delete_firewall_policy to manage it.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_firewall_policies(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_wlan(
    ctx: Context,
    wlan: Annotated[
        Annotated[str, Field(description="WLAN id or SSID name to update.")],
        Field(description="WLAN id or SSID name to update."),
    ],
    enabled: Annotated[
        Annotated[bool | None, Field(description="Enable or disable the SSID.")],
        Field(description="Enable or disable the SSID."),
    ] = None,
    hide_ssid: Annotated[
        Annotated[bool | None, Field(description="Hide the SSID from beacon broadcasts.")],
        Field(description="Hide the SSID from beacon broadcasts."),
    ] = None,
    passphrase: Annotated[
        Annotated[str | None, Field(description="New WiFi password (minimum 8 characters).")],
        Field(description="New WiFi password (minimum 8 characters)."),
    ] = None,
    wpa3_support: Annotated[
        Annotated[bool | None, Field(description="Enable WPA3 support on the SSID.")],
        Field(description="Enable WPA3 support on the SSID."),
    ] = None,
    wpa3_transition: Annotated[
        Annotated[
            bool | None,
            Field(description="WPA2/WPA3 transition mode (keeps WPA2 for legacy clients)."),
        ],
        Field(description="WPA2/WPA3 transition mode (keeps WPA2 for legacy clients)."),
    ] = None,
    pmf_mode: Annotated[
        Annotated[
            str | None,
            Field(
                description='Protected Management Frames mode — "disabled", "optional", or "required".'
            ),
        ],
        Field(
            description='Protected Management Frames mode — "disabled", "optional", or "required".'
        ),
    ] = None,
    bss_transition: Annotated[
        Annotated[bool | None, Field(description="Enable 802.11k/v band and AP steering.")],
        Field(description="Enable 802.11k/v band and AP steering."),
    ] = None,
    fast_roaming_enabled: Annotated[
        Annotated[bool | None, Field(description="Enable 802.11r fast roaming.")],
        Field(description="Enable 802.11r fast roaming."),
    ] = None,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Update a wireless network (SSID); only the fields you provide change.

    Mutating operation: applied immediately and persisted on the UniFi console.
    Any single field updates the matching SSID (resolved by ID or name). Requoting
    passphrase sets the WiFi password; pmf_mode is disabled|optional|required. Inspect
    with get_wlans.

    Args:
        wlan: WLAN id or SSID name to update.
        enabled: Enable or disable the SSID.
        hide_ssid: Hide the SSID from beacon broadcasts.
        passphrase: New WiFi password (minimum 8 characters).
        wpa3_support: Enable WPA3 support on the SSID.
        wpa3_transition: WPA2/WPA3 transition mode (keeps WPA2 for legacy clients).
        pmf_mode: Protected Management Frames mode — "disabled", "optional", or "required".
        bss_transition: Enable 802.11k/v band and AP steering.
        fast_roaming_enabled: Enable 802.11r fast roaming.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.update_wlan(
        ctx,
        wlan,
        enabled,
        hide_ssid,
        passphrase,
        wpa3_support,
        wpa3_transition,
        pmf_mode,
        bss_transition,
        fast_roaming_enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_wlan(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="SSID broadcast name.")],
        Field(description="SSID broadcast name."),
    ],
    passphrase: Annotated[
        Annotated[str, Field(description="WiFi password, 8-63 characters.")],
        Field(description="WiFi password, 8-63 characters."),
    ],
    network_conf_id: Annotated[
        Annotated[
            str | None,
            Field(description="Network id to attach the SSID to; omit for the default LAN."),
        ],
        Field(description="Network id to attach the SSID to; omit for the default LAN."),
    ] = None,
    wpa3_transition: Annotated[
        Annotated[bool, Field(description="Use WPA2/WPA3 transition mode. Defaults to True.")],
        Field(description="Use WPA2/WPA3 transition mode. Defaults to True."),
    ] = True,
    hide_ssid: Annotated[
        Annotated[
            bool, Field(description="Broadcast the SSID hidden when True. Defaults to False.")
        ],
        Field(description="Broadcast the SSID hidden when True. Defaults to False."),
    ] = False,
    is_guest: Annotated[
        Annotated[
            bool,
            Field(description="Mark the SSID as an isolated guest network. Defaults to False."),
        ],
        Field(description="Mark the SSID as an isolated guest network. Defaults to False."),
    ] = False,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Create a wireless network (SSID) with WPA2/WPA3 transition security by default.

    Mutating operation: applied immediately and persisted on the UniFi console.
    Passphrase must be 8-63 characters. WPA2/WPA3 transition is enabled unless
    wpa3_transition is False, keeping WPA2 for legacy clients. Attach to a VLAN via
    network_conf_id, or mark is_guest for an isolated guest SSID. Inspect with get_wlans.

    Args:
        name: SSID broadcast name.
        passphrase: WiFi password, 8-63 characters.
        network_conf_id: Network id to attach the SSID to; omit for the default LAN.
        wpa3_transition: Use WPA2/WPA3 transition mode. Defaults to True.
        hide_ssid: Broadcast the SSID hidden when True. Defaults to False.
        is_guest: Mark the SSID as an isolated guest network. Defaults to False.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.create_wlan(
        ctx,
        name,
        passphrase,
        network_conf_id,
        wpa3_transition,
        hide_ssid,
        is_guest,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_wlan(
    ctx: Context,
    wlan: Annotated[
        Annotated[str, Field(description="WLAN id or SSID name to delete.")],
        Field(description="WLAN id or SSID name to delete."),
    ],
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to delete. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to delete. Defaults to False."),
    ] = False,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Delete a wireless network (SSID).

    Mutating operation: removed immediately and persisted on the UniFi console.
    Requires confirm=true because deleting an SSID disconnects its clients. Resolve the
    target by ID or name and review get_wlans first.

    Args:
        wlan: WLAN id or SSID name to delete.
        confirm: Safety gate: must be True to delete. Defaults to False.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.delete_wlan(ctx, wlan, confirm, site, device)


@mcp.tool()
async def create_firewall_policy(
    ctx: Context,
    name: Annotated[
        Annotated[str, Field(description="Policy name (used for display and zone inference).")],
        Field(description="Policy name (used for display and zone inference)."),
    ],
    action: Annotated[
        Annotated[str, Field(description='Packet decision — "ALLOW", "BLOCK", or "REJECT".')],
        Field(description='Packet decision — "ALLOW", "BLOCK", or "REJECT".'),
    ],
    src_zone_id: Annotated[
        Annotated[str, Field(description="Source zone id (from get_firewall_policies).")],
        Field(description="Source zone id (from get_firewall_policies)."),
    ],
    dst_zone_id: Annotated[
        Annotated[str, Field(description="Destination zone id (from get_firewall_policies).")],
        Field(description="Destination zone id (from get_firewall_policies)."),
    ],
    protocol: Annotated[
        Annotated[
            str,
            Field(
                description='Protocol selector — "all", "tcp", "udp", "tcp_udp", "icmp", "igmp", or "icmpv6".'
            ),
        ],
        Field(
            description='Protocol selector — "all", "tcp", "udp", "tcp_udp", "icmp", "igmp", or "icmpv6".'
        ),
    ] = "all",
    description: Annotated[
        Annotated[str | None, Field(description="Optional human-readable description.")],
        Field(description="Optional human-readable description."),
    ] = None,
    client_macs: Annotated[
        Annotated[
            list[str] | None,
            Field(description="Restrict the source to these client MAC addresses."),
        ],
        Field(description="Restrict the source to these client MAC addresses."),
    ] = None,
    index: Annotated[
        Annotated[
            int | None,
            Field(
                description="Rule order index; lower values evaluate earlier. Omit for auto-order."
            ),
        ],
        Field(description="Rule order index; lower values evaluate earlier. Omit for auto-order."),
    ] = None,
    enabled: Annotated[
        Annotated[bool, Field(description="Create the policy enabled. Defaults to True.")],
        Field(description="Create the policy enabled. Defaults to True."),
    ] = True,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Create a zone-based firewall policy (UniFi Network 9+).

    Mutating operation: applied immediately and persisted on the UniFi console.
    Action is ALLOW, BLOCK, or REJECT across the src_zone_id to dst_zone_id pair.
    Lower index evaluates earlier. A controller-generated "(Return)" companion rule is
    typically added. Requires zone ids from get_firewall_policies; review there first.

    Args:
        name: Policy name (used for display and zone inference).
        action: Packet decision — "ALLOW", "BLOCK", or "REJECT".
        src_zone_id: Source zone id (from get_firewall_policies).
        dst_zone_id: Destination zone id (from get_firewall_policies).
        protocol: Protocol selector — "all", "tcp", "udp", "tcp_udp", "icmp", "igmp", or "icmpv6".
        description: Optional human-readable description.
        client_macs: Restrict the source to these client MAC addresses.
        index: Rule order index; lower values evaluate earlier. Omit for auto-order.
        enabled: Create the policy enabled. Defaults to True.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.create_firewall_policy(
        ctx,
        name,
        action,
        src_zone_id,
        dst_zone_id,
        protocol,
        description,
        client_macs,
        index,
        enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_firewall_policy_enabled(
    ctx: Context,
    policy_id: Annotated[
        Annotated[str, Field(description="Policy id to toggle (from get_firewall_policies).")],
        Field(description="Policy id to toggle (from get_firewall_policies)."),
    ],
    enabled: Annotated[
        Annotated[bool, Field(description="True to enable, False to disable.")],
        Field(description="True to enable, False to disable."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Enable or disable a zone-based firewall policy.

    Mutating operation: applied immediately and persisted on the UniFi console.
    Targets the policy by id from get_firewall_policies. Predefined controller policies
    can be toggled but not deleted. Inspect state with get_firewall_policies.

    Args:
        policy_id: Policy id to toggle (from get_firewall_policies).
        enabled: True to enable, False to disable.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.set_firewall_policy_enabled(ctx, policy_id, enabled, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_firewall_policy(
    ctx: Context,
    policy_id: Annotated[
        Annotated[str, Field(description="Policy id to delete (from get_firewall_policies).")],
        Field(description="Policy id to delete (from get_firewall_policies)."),
    ],
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to delete. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to delete. Defaults to False."),
    ] = False,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Delete a zone-based firewall policy.

    Mutating operation: removed immediately and persisted on the UniFi console.
    Requires confirm=true because removing a policy changes traffic flow. Predefined
    controller policies are refused. Target by id from get_firewall_policies.

    Args:
        policy_id: Policy id to delete (from get_firewall_policies).
        confirm: Safety gate: must be True to delete. Defaults to False.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.delete_firewall_policy(ctx, policy_id, confirm, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_firewall_rule(
    ctx: Context,
    name: Annotated[str, Field(description="Unique rule name")],
    action: Annotated[str, Field(description='Action — "accept", "drop", or "reject"')],
    protocol: Annotated[
        str, Field(description='Protocol — "tcp", "udp", "icmp", "all", or IANA number')
    ],
    dst_port: Annotated[
        str | int | None,
        Field(description="Destination port or range (e.g., '80', '80-443')."),
    ] = None,
    src_zone: Annotated[
        str | None,
        Field(description="Source zone ID (from get_firewall_policies)."),
    ] = None,
    dst_zone: Annotated[
        str | None,
        Field(description="Destination zone ID."),
    ] = None,
    src_port: Annotated[
        str | int | None,
        Field(description="Source port or range."),
    ] = None,
    logging: Annotated[bool, Field(description="Enable logging for matches.")] = False,
    enabled: Annotated[
        bool, Field(description="Whether rule is active on creation. Defaults to True.")
    ] = True,
    site: Annotated[
        str, Field(description='Site to operate on. Defaults to "default".')
    ] = "default",
    device: Annotated[
        str | None,
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Create a legacy firewall rule (UniFi Network <9 or traditional API).

    Mutating operation: applied immediately and persisted on the controller.
    For zone-based policies (Network 9+), prefer create_firewall_policy.
    Review existing rules with get_firewall_rules first.

    Args:
        name: Unique rule name
        action: Action — "accept", "drop", or "reject"
        protocol: Protocol — "tcp", "udp", "icmp", "all", or IANA number
        dst_port: Destination port or range (e.g., "80", "80-443")
        src_zone: Source zone ID (from get_firewall_policies)
        dst_zone: Destination zone ID
        src_port: Source port or range
        logging: Enable logging for matches
        enabled: Whether rule is active on creation. Defaults to True.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific console; omit for default.

    Returns:
        Created firewall rule configuration
    """
    return await site_tools.create_firewall_rule(
        ctx,
        name,
        action,
        protocol,
        dst_port,
        src_zone,
        dst_zone,
        src_port,
        logging,
        enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_firewall_rule(
    ctx: Context,
    rule_id: Annotated[str, Field(description="Firewall rule ID (from get_firewall_rules).")],
    name: Annotated[str | None, Field(description="New rule name.")] = None,
    action: Annotated[
        str | None, Field(description='Action — "accept", "drop", or "reject"')
    ] = None,
    protocol: Annotated[
        str | None, Field(description='Protocol — "tcp", "udp", "icmp", "all", or IANA number')
    ] = None,
    dst_port: Annotated[
        str | int | None,
        Field(description="Destination port or range."),
    ] = None,
    src_zone: Annotated[str | None, Field(description="Source zone ID.")] = None,
    dst_zone: Annotated[str | None, Field(description="Destination zone ID.")] = None,
    src_port: Annotated[str | int | None, Field(description="Source port or range.")] = None,
    logging: Annotated[bool | None, Field(description="Enable/disable logging.")] = None,
    enabled: Annotated[bool | None, Field(description="Enable/disable the rule.")] = None,
    site: Annotated[
        str, Field(description='Site to operate on. Defaults to "default".')
    ] = "default",
    device: Annotated[
        str | None,
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Update a legacy firewall rule. Only provided fields are changed.

    Mutating operation: applied immediately and persisted on the controller.
    Use get_firewall_rules to find the rule ID first.

    Args:
        rule_id: Firewall rule ID (from get_firewall_rules)
        name: New rule name
        action: Action — "accept", "drop", or "reject"
        protocol: Protocol — "tcp", "udp", "icmp", "all", or IANA number
        dst_port: Destination port or range
        src_zone: Source zone ID
        dst_zone: Destination zone ID
        src_port: Source port or range
        logging: Enable/disable logging
        enabled: Enable/disable the rule
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific console; omit for default.

    Returns:
        Updated firewall rule configuration
    """
    return await site_tools.update_firewall_rule(
        ctx,
        rule_id,
        name,
        action,
        protocol,
        dst_port,
        src_zone,
        dst_zone,
        src_port,
        logging,
        enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_firewall_rule(
    ctx: Context,
    rule_id: Annotated[str, Field(description="Firewall rule ID (from get_firewall_rules).")],
    confirm: Annotated[bool, Field(description="Must be True to actually delete.")] = False,
    site: Annotated[
        str, Field(description='Site to operate on. Defaults to "default".')
    ] = "default",
    device: Annotated[
        str | None,
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Delete a legacy firewall rule. Requires confirm=True.

    Mutating operation: permanently removes the rule from the controller.

    Args:
        rule_id: Firewall rule ID (from get_firewall_rules)
        confirm: Must be True to actually delete
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific console; omit for default.

    Returns:
        Deletion status
    """
    return await site_tools.delete_firewall_rule(ctx, rule_id, confirm, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_port_forwards(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Get all port forwarding rules for a site.

    Read-only operation: returns each rule mapping an external port+protocol to an
    internal IP+port on the gateway. Use this to audit forwards and to find a rule id
    before delete_port_forward, or create_port_forward to add one.

    Args:
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.get_port_forwards(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_port_forward(
    ctx: Context,
    name: Annotated[
        Annotated[
            str, Field(description="Unique rule identifier used to find/delete the rule later.")
        ],
        Field(description="Unique rule identifier used to find/delete the rule later."),
    ],
    dst_port: Annotated[
        Annotated[
            str, Field(description="Internal destination port (1-65535) on the target host.")
        ],
        Field(description="Internal destination port (1-65535) on the target host."),
    ],
    fwd_ip: Annotated[
        Annotated[
            str, Field(description="LAN IP of the internal host receiving forwarded traffic.")
        ],
        Field(description="LAN IP of the internal host receiving forwarded traffic."),
    ],
    fwd_port: Annotated[
        Annotated[str, Field(description="External listening port (1-65535) on the WAN.")],
        Field(description="External listening port (1-65535) on the WAN."),
    ],
    proto: Annotated[
        Annotated[str, Field(description='IP protocol to forward — "tcp", "udp", or "both".')],
        Field(description='IP protocol to forward — "tcp", "udp", or "both".'),
    ] = "tcp_udp",
    enabled: Annotated[
        Annotated[bool, Field(description="Whether active on creation. Defaults to True.")],
        Field(description="Whether active on creation. Defaults to True."),
    ] = True,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional device name to target a specific console; omit for default."
            ),
        ],
        Field(description="Optional device name to target a specific console; omit for default."),
    ] = None,
):
    """Create a port-forwarding rule that opens an external WAN port and maps it to an internal host/port.

    Mutating operation: applied immediately and persisted on the UniFi console.
    Review existing rules with get_port_forwards first; remove with delete_port_forward.
    Prefer create_firewall_policy for zone-based/stateful filtering.

    Args:
        name: Unique rule identifier used to find/delete the rule later.
        dst_port: Internal destination port (1-65535) on the target host.
        fwd_ip: LAN IP of the internal host receiving forwarded traffic.
        fwd_port: External listening port (1-65535) on the WAN.
        proto: IP protocol to forward — "tcp", "udp", or "both".
        enabled: Whether active on creation. Defaults to True.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.
    """
    return await site_tools.create_port_forward(
        ctx, name, dst_port, fwd_ip, fwd_port, proto, enabled, site, device
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_port_forward(
    ctx: Context,
    rule_id: Annotated[
        Annotated[
            str, Field(description="Port forward rule id to delete (from get_port_forwards).")
        ],
        Field(description="Port forward rule id to delete (from get_port_forwards)."),
    ],
    confirm: Annotated[
        Annotated[
            bool, Field(description="Safety gate: must be True to delete. Defaults to False.")
        ],
        Field(description="Safety gate: must be True to delete. Defaults to False."),
    ] = False,
    site: Annotated[
        Annotated[str, Field(description='Site to operate on. Defaults to "default".')],
        Field(description='Site to operate on. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console name to target a specific UniFi device; omit for default."
            ),
        ],
        Field(
            description="Optional console name to target a specific UniFi device; omit for default."
        ),
    ] = None,
):
    """Delete a port forwarding rule.

    Mutating operation: removed immediately and persisted on the UniFi console.
    Requires confirm=true because removing a forward closes external access. Target by
    rule id from get_port_forwards.

    Args:
        rule_id: Port forward rule id to delete (from get_port_forwards).
        confirm: Safety gate: must be True to delete. Defaults to False.
        site: Site to operate on. Defaults to "default".
        device: Optional console name to target a specific UniFi device; omit for
            default.
    """
    return await site_tools.delete_port_forward(ctx, rule_id, confirm, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_all_sites_health(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return a health overview for every site managed by one UniFi console.

    Read-only operation: it walks each site on the targeted console and returns
    a compact health snapshot per site (status, score, and key counts). Unlike
    get_global_health, this stays within a single console; unlike get_site_health,
    it covers all sites at once rather than one. Use get_global_health when you
    need cross-console aggregation; prefer get_site_health when you want full
    per-subsystem detail for a single named site.

    Args:
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.get_all_sites_health(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_routing_table(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return the live Layer-3 routing table for a site's gateway.

    Read-only operation: it lists each route with destination, next-hop,
    interface, and source/metric so you can verify static and learned routes.
    Use get_networks to inspect configured VLAN/subnet definitions rather than
    active forwarding paths.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await site_tools.get_routing_table(ctx, site, device)


# =============================================================================
# Statistics & Monitoring Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_network_health(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return a single overall health summary for one site's network.

    Read-only operation: it aggregates WAN/LAN/WLAN status, a composite health
    score, and device/user tallies into one condensed report. Use get_site_health
    when you need full per-subsystem detail for that site, get_all_sites_health
    for a multi-site sweep on one console, or get_global_health for cross-console
    aggregation.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_network_health(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_recent_events(
    ctx: Context,
    limit: Annotated[
        Annotated[int, Field(description="Maximum number of events to return (default 50).")],
        Field(description="Maximum number of events to return (default 50)."),
    ] = 50,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return recent network events (connections, roams, admin actions) for a site.

    Read-only operation: it surfaces the newest logged events with type,
    timestamp, and subject so you can trace what changed on the network. Use
    get_alarms when you only care about active fault/warning alarms rather than
    the full event stream; use get_optimization_recommendations or
    analyze_network_issues for interpreted, actionable findings.

    Args:
        limit: Maximum number of events to return (default 50).
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_recent_events(ctx, limit, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_alarms(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return the currently active alarms (faults and warnings) for a site.

    Read-only operation: it lists unacknowledged/active alarms with severity and
    message so you can see what needs attention. Use get_recent_events for the
    broad event feed including non-alarm activity; clear them with
    archive_all_alarms once handled, or use analyze_network_issues for a
    consolidated interpretation of alarms and health.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_alarms(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def archive_all_alarms(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Acknowledge and archive every active alarm on a site.

    Non-destructive state change: it marks open alarms as archived so they no
    longer show in get_alarms; no device configuration is modified. Use
    get_alarms first to review what will be cleared; prefer
    analyze_network_issues when you want findings without clearing alarm state.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.archive_all_alarms(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def run_speed_test(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Start an on-demand WAN speed test from the site gateway.

    Mutating/long-running operation: it triggers a test against the speed-test
    endpoint and returns a handle or immediate result; poll get_speed_test_status
    for completion. Use get_speed_test_status to read the latest result without
    starting a new test.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.run_speed_test(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_speed_test_status(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return the latest WAN speed-test result and run state for a site.

    Read-only operation: it reports download/upload/latency from the most recent
    test and whether a test is in progress. Use run_speed_test to initiate a new
    measurement; this does not start one.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_speed_test_status(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_dpi_stats(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return Deep Packet Inspection application-breakdown statistics for a site.

    Read-only operation: it ranks traffic by detected application/category so you
    can see what protocols and apps dominate usage. Use get_traffic_summary for a
    lighter volume-only overview, get_traffic_analysis for time-windowed trends
    and top talkers, or get_client_traffic for a single client's DPI view.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_dpi_stats(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_traffic_summary(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """Return a condensed traffic-volume summary for a site.

    Read-only operation: it reports overall throughput and totals without the
    per-app or time-series detail. Use get_dpi_stats for application-level
    breakdown, get_traffic_analysis for windowed trends and top talkers, or
    get_client_traffic for a specific client.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await stat_tools.get_traffic_summary(ctx, site, device)


# =============================================================================
# AI Insight Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def analyze_network_issues(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Analyze a site and return a structured report of potential issues.

    Read-only operation: it aggregates device health, client connection problems,
    interference, firmware status, and recent alarms into an AI-friendly summary
    of what may be wrong. Use get_alarms for the raw active-alarm list,
    get_device_health_summary for device-only status, or
    get_optimization_recommendations when you want improvement suggestions rather
    than a fault report.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.analyze_network_issues(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_optimization_recommendations(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Analyze a site's configuration and return optimization recommendations.

    Read-only operation: it checks channel selection, TX power, VLAN efficiency,
    port configurations, and bandwidth utilization to suggest improvements. Use
    analyze_network_issues when you want a fault/issue report instead of
    proactive tuning advice, or get_device_health_summary for device status only.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.get_optimization_recommendations(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_experience_report(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Generate a client experience report with connection-quality metrics for a site.

    Read-only operation: it summarizes signal-strength distribution, roaming
    stats, failed connections, and problematic clients across the site. Use
    troubleshoot_client for a deep dive on one specific client, or
    get_device_health_summary for the infrastructure view rather than client-side.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.get_client_experience_report(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_health_summary(
    ctx: Context,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Summarize device health across all APs, switches, and routers at a site.

    Read-only operation: it reports uptime, load, memory, temperature, firmware
    versions, and devices needing attention. Use get_site_health or
    get_network_health for overall/site status, analyze_network_issues for
    issues folded into a report, or get_client_experience_report for the client
    perspective.

    Args:
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.get_device_health_summary(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_traffic_analysis(
    ctx: Context,
    hours: Annotated[
        Annotated[int, Field(description="Lookback window in hours from now (default 24).")],
        Field(description="Lookback window in hours from now (default 24)."),
    ] = 24,
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Analyze site traffic patterns over a configurable time window.

    Read-only operation: it reports top talkers, application breakdown (DPI),
    bandwidth trends, and unusual activity for the lookback period. Use
    get_traffic_summary for a quick volume-only snapshot, get_dpi_stats for the
    app breakdown without the time series, or get_client_traffic for one client.

    Args:
        hours: Lookback window in hours from now (default 24).
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.get_traffic_analysis(ctx, hours, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def troubleshoot_client(
    ctx: Context,
    mac: Annotated[
        Annotated[str, Field(description="MAC address of the client to troubleshoot.")],
        Field(description="MAC address of the client to troubleshoot."),
    ],
    site: Annotated[
        Annotated[str, Field(description='Site to query. Defaults to "default".')],
        Field(description='Site to query. Defaults to "default".'),
    ] = "default",
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional console/device name to target a specific UniFi console; omit to use the default."
            ),
        ],
        Field(
            description="Optional console/device name to target a specific UniFi console; omit to use the default."
        ),
    ] = None,
):
    """
    Run a deep-dive troubleshooting analysis for one specific client.

    Read-only operation: it examines connection history, signal quality, AP
    associations, roaming events, and potential issues for the named client. Use
    get_client_experience_report for a site-wide client-quality overview, or
    get_client_details for the raw record of one client without the analysis.

    Args:
        mac: MAC address of the client to troubleshoot.
        site: Site to query. Defaults to "default".
        device: Optional console/device name to target a specific UniFi console;
            omit to use the default.
    """
    return await insight_tools.troubleshoot_client(ctx, mac, site, device)


# =============================================================================
# UniFi Protect Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_cameras(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """List every UniFi Protect camera with its online state and identity.

    Read-only operation: it returns a summary per camera (name, model, state,
    and connection status) for the targeted Protect console. Use this to
    discover the camera_id values needed by get_camera_details,
    get_camera_snapshot, get_camera_health_summary, and the event tools. Use
    get_camera_health_summary when you only need aggregate connected/disconnected
    counts rather than the full per-camera list.

    Args:
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.list_cameras(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_details(
    ctx: Context,
    camera_id: Annotated[
        Annotated[str, Field(description="Protect camera identifier or name to look up.")],
        Field(description="Protect camera identifier or name to look up."),
    ],
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Get the full configuration and runtime record for one Protect camera.

    Read-only operation: it returns the camera's model, firmware, resolution,
    recording mode, privacy/IR state, connection state, and live statistics. The
    camera is resolved by ID first and then by name, so either form is accepted.
    Use list_cameras first to find the camera_id; use get_camera_snapshot to
    capture an image, or get_camera_health_summary for a connectivity-only view.

    Args:
        camera_id: Protect camera identifier or name to look up.
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_camera_details(ctx, camera_id, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_snapshot(
    ctx: Context,
    camera_id: Annotated[
        Annotated[str, Field(description="Protect camera identifier or name to capture from.")],
        Field(description="Protect camera identifier or name to capture from."),
    ],
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
    width: Annotated[
        Annotated[
            int | None,
            Field(
                description="Optional target pixel width for the snapshot; native width if unset."
            ),
        ],
        Field(description="Optional target pixel width for the snapshot; native width if unset."),
    ] = None,
    height: Annotated[
        Annotated[
            int | None,
            Field(
                description="Optional target pixel height for the snapshot; native height if unset."
            ),
        ],
        Field(description="Optional target pixel height for the snapshot; native height if unset."),
    ] = None,
):
    """Capture a still image from a connected Protect camera as a base64 JPEG.

    Read-only operation: it requests a live frame from the camera and returns it
    as a base64-encoded JPEG plus camera name and id. If width and/or height are
    provided the image is resized to those pixel dimensions; if omitted the
    camera's native resolution is returned. A camera that is not in the
    CONNECTED state returns a success=false result rather than an image. Use
    get_camera_details to confirm the camera is online before calling.

    Args:
        camera_id: Protect camera identifier or name to capture from.
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
        width: Optional target pixel width for the snapshot; native width if unset.
        height: Optional target pixel height for the snapshot; native height if unset.
    """
    return await protect_tools.get_camera_snapshot(ctx, camera_id, device, width, height)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_camera(
    ctx: Context,
    camera: Annotated[str, Field(description="Protect camera identifier or name to update.")],
    name: Annotated[str | None, Field(description="New camera name.")] = None,
    is_recording_enabled: Annotated[
        bool | None, Field(description="Enable/disable recording.")
    ] = None,
    recording_mode: Annotated[
        str | None,
        Field(description='Recording mode — "always", "motion", "smart_detect", "never".'),
    ] = None,
    device: Annotated[
        str | None,
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Update a camera's configuration.

    Mutating operation: changes are applied immediately and persisted on the
    Protect console. Requires username/password configured for the device.

    Args:
        camera: Camera ID or name (resolved by name if not an ID)
        name: New camera name
        is_recording_enabled: Enable/disable recording
        recording_mode: Recording mode — "always", "motion", "smart_detect", "never"
        device: Optional Protect console name to target a specific UniFi Protect device; omit for first configured Protect device.

    Returns:
        Updated camera configuration
    """
    return await protect_tools.update_camera(
        ctx, camera, name, is_recording_enabled, recording_mode, device
    )


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_system_info(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Return UniFi Protect system information for one console, including device counts.

    Read-only operation: it reports the Protect system version, NVR/storage
    status, and counts of cameras and accessories managed by the targeted
    console. Use this for a high-level overlay of a Protect deployment; use
    list_cameras or get_protect_accessories for the individual device inventory,
    or get_camera_health_summary for camera connectivity.

    Args:
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_protect_system_info(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_health_summary(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Summarize the connectivity and health of all cameras on one Protect console.

    Read-only operation: it partitions cameras into connected and disconnected
    sets, returns an overall status of "healthy" or "degraded", lists each
    disconnected camera as a critical issue, and offers remediation
    recommendations. Use this for a fleet-wide connectivity check; use
    list_cameras for the full per-camera detail or get_camera_details for one
    camera's complete record.

    Args:
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_camera_health_summary(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_liveviews(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """List all configured UniFi Protect liveviews (camera view layouts).

    Read-only operation: it returns each liveview's name, id, and the cameras
    and layout it includes on the targeted console. Use this to discover view
    groupings for dashboards or to confirm which cameras belong to a named
    liveview; it does not return footage or snapshots.

    Args:
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_liveviews(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_accessories(
    ctx: Context,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Inventory all UniFi Protect accessories: lights, sensors, chimes, and viewers.

    Read-only operation: it queries each accessory type on the targeted console
    and returns the raw records grouped by type along with a per-type count
    summary. Use this to audit Protect peripherals alongside cameras; it does not
    return camera devices (see list_cameras) nor event history.

    Args:
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_protect_accessories(ctx, device)


# =============================================================================
# UniFi Protect Event Tools (require username/password)
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_motion_events(
    ctx: Context,
    hours: Annotated[
        Annotated[int, Field(description="Lookback window in hours from now (default 24).")],
        Field(description="Lookback window in hours from now (default 24)."),
    ] = 24,
    limit: Annotated[
        Annotated[int, Field(description="Maximum number of events to return (default 50).")],
        Field(description="Maximum number of events to return (default 50)."),
    ] = 50,
    camera_id: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect camera identifier or name to filter events to one camera; omit for all cameras."
            ),
        ],
        Field(
            description="Optional Protect camera identifier or name to filter events to one camera; omit for all cameras."
        ),
    ] = None,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Return recent camera motion events, resolved to camera names and timestamps.

    Read-only operation: it queries Protect motion events over the lookback
    window, maps each event to its camera name and a human-readable timestamp,
    and returns the count and per-event list. Requires Protect username/password
    credentials configured for the console. Use get_smart_detections instead when
    you need AI classification (person/vehicle/animal/package) rather than raw
    motion; use get_protect_event_summary for aggregate counts.

    Args:
        hours: Lookback window in hours from now (default 24).
        limit: Maximum number of events to return (default 50).
        camera_id: Optional Protect camera identifier or name to filter events to
            one camera; omit for all cameras.
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_motion_events(ctx, hours, limit, camera_id, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_smart_detections(
    ctx: Context,
    hours: Annotated[
        Annotated[int, Field(description="Lookback window in hours from now (default 24).")],
        Field(description="Lookback window in hours from now (default 24)."),
    ] = 24,
    limit: Annotated[
        Annotated[int, Field(description="Maximum number of events to return (default 50).")],
        Field(description="Maximum number of events to return (default 50)."),
    ] = 50,
    detection_type: Annotated[
        Annotated[
            str | None,
            Field(
                description='Optional class filter - one of "person", "vehicle", "animal", "package"; omit for all smart-detection types.'
            ),
        ],
        Field(
            description='Optional class filter - one of "person", "vehicle", "animal", "package"; omit for all smart-detection types.'
        ),
    ] = None,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Return AI smart-detection events (person, vehicle, animal, package) with types.

    Read-only operation: it queries Protect smart-detection events over the
    lookback window, maps each to its camera name and timestamp, and includes the
    smartDetectTypes and confidence score. Requires Protect username/password
    credentials configured for the console. Use detection_type to narrow to one
    class (e.g. "person"); use get_motion_events for raw motion without
    classification, or get_protect_event_summary for aggregate counts.

    Args:
        hours: Lookback window in hours from now (default 24).
        limit: Maximum number of events to return (default 50).
        detection_type: Optional class filter - one of "person", "vehicle",
            "animal", "package"; omit for all smart-detection types.
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_smart_detections(ctx, hours, limit, detection_type, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_event_summary(
    ctx: Context,
    hours: Annotated[
        Annotated[int, Field(description="Lookback window in hours from now (default 24).")],
        Field(description="Lookback window in hours from now (default 24)."),
    ] = 24,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Summarize all Protect events (motion, smart detections, doorbell) over a window.

    Read-only operation: it aggregates event counts by type and camera activity
    for the lookback window on the targeted console. Requires Protect
    username/password credentials configured for the console. Use this for a
    single high-level tally; use get_motion_events or get_smart_detections for
    the underlying event records, or get_recent_protect_activity for the latest
    raw events.

    Args:
        hours: Lookback window in hours from now (default 24).
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_event_summary(ctx, hours, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_recent_protect_activity(
    ctx: Context,
    limit: Annotated[
        Annotated[
            int, Field(description="Maximum number of recent events to return (default 20).")
        ],
        Field(description="Maximum number of recent events to return (default 20)."),
    ] = 20,
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
):
    """Return the most recent Protect events across all cameras as a quick overview.

    Read-only operation: it fetches the latest events (up to limit) for the
    targeted console with camera names and timestamps resolved. Requires Protect
    username/password credentials configured for the console. Use this for a fast
    "what just happened" check; use get_protect_event_summary for aggregate
    counts or get_motion_events/get_smart_detections for filtered, time-windowed
    history.

    Args:
        limit: Maximum number of recent events to return (default 20).
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
    """
    return await protect_tools.get_recent_activity(ctx, limit, device)


# =============================================================================
# Multi-Device Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_unifi_devices(ctx: Context):
    """List every UniFi device (console) configured for this server.

    Read-only operation: it returns each configured device's name, controller
    URL, site, and the services it exposes (network, protect), plus convenience
    lists of network-only and protect-only device names. This is the authoritative
    source for the device name accepted by every other tool's optional ``device``
    parameter. Use get_global_inventory / get_global_health when you instead want
    aggregated data across those consoles rather than the console roster itself.

    Returns:
        Dict with total_devices, a per-device list, and network_devices /
        protect_devices name lists.
    """
    devices = settings.devices
    return {
        "total_devices": len(devices),
        "devices": [
            {
                "name": d.name,
                "url": d.url,
                "services": d.services,
                "site": d.site,
            }
            for d in devices
        ],
        "network_devices": [d.name for d in settings.get_network_devices()],
        "protect_devices": [d.name for d in settings.get_protect_devices()],
    }


# ---------------------------------------------------------------------------
# Multi-site orchestration tools
# ---------------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_inventory(ctx: Context) -> dict:
    """Aggregate the full device inventory across every configured network console.

    Read-only operation: it calls list_devices on each network-enabled device and
    merges the results into one list, tagging every entry with its source device
    name, plus any per-console errors. Use this to see every AP, switch, gateway,
    and router across all sites in one view; use list_unifi_devices for the
    console roster itself, or get_global_health / get_global_client_summary for
    aggregated health and client counts rather than the raw device records.

    Returns:
        Dict with total_devices, the merged devices list (each tagged
        _source_device), and an errors list when a console fails.
    """
    return await multisite_tools.get_global_inventory(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_health(ctx: Context) -> dict:
    """Aggregate site health across every configured network console into one report.

    Read-only operation: it collects per-subsystem site health (WAN/LAN/WLAN
    status, health score, and device/user counts) from each network-enabled
    device and folds them into a unified view with an overall "healthy" or
    "degraded" verdict. Use this for a single fleet-wide health check; use
    get_global_inventory for the device roster, get_global_client_summary for
    client counts, or get_site_health on a single console for full subsystem
    detail.

    Returns:
        Dict with overall_status, device_count, a per-device subsystems
        breakdown, and an errors list when a console fails.
    """
    return await multisite_tools.get_global_health(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_client_summary(ctx: Context) -> dict:
    """Summarize connected clients across every configured network console.

    Read-only operation: it aggregates active clients from each network-enabled
    device and computes totals (wireless/wired/blocked), the top 10 talkers by
    usage, and a per-device client count. Use this for fleet-wide client
    visibility; use get_global_inventory for the device roster, get_global_health
    for subsystem health, or list_clients on a single console for the full
    per-client detail.

    Returns:
        Dict with total_clients, wireless/wired/blocked counts, top_talkers,
        per_device counts, and an errors list when a console fails.
    """
    return await multisite_tools.get_global_client_summary(ctx)


def main():
    """Run the MCP server."""
    logger.info("Starting UniFi MCP Server")
    device_count = len(settings.devices)
    if device_count > 0:
        logger.info(f"Configured devices: {settings.get_device_names()}")
    else:
        logger.warning("No devices configured!")
    if settings.transport == "stdio":
        mcp.run()
    else:
        mcp.run(
            "streamable-http",
            host=settings.http_host,
            port=settings.http_port,
            streamable_http_path=settings.http_path,
        )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def export_camera_clip(
    ctx: Context,
    camera: Annotated[
        Annotated[
            str, Field(description="Protect camera identifier or name to export footage from.")
        ],
        Field(description="Protect camera identifier or name to export footage from."),
    ],
    start_ts: Annotated[
        Annotated[int, Field(description="Clip start time as a Unix epoch timestamp (seconds).")],
        Field(description="Clip start time as a Unix epoch timestamp (seconds)."),
    ],
    end_ts: Annotated[
        Annotated[
            int,
            Field(
                description="Clip end time as a Unix epoch timestamp (seconds); must be after start_ts."
            ),
        ],
        Field(
            description="Clip end time as a Unix epoch timestamp (seconds); must be after start_ts."
        ),
    ],
    output_path: Annotated[
        Annotated[
            str,
            Field(
                description="Destination filename (or path relative to the export directory); it is confined to the server's export directory."
            ),
        ],
        Field(
            description="Destination filename (or path relative to the export directory); it is confined to the server's export directory."
        ),
    ],
    device: Annotated[
        Annotated[
            str | None,
            Field(
                description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
            ),
        ],
        Field(
            description="Optional Protect console name to target a specific UniFi Protect device; omit to use the first Protect-enabled device."
        ),
    ] = None,
    confirm: Annotated[
        Annotated[
            bool,
            Field(
                description="Safety confirmation required for this file-writing operation; the export returns a failure message until set to true."
            ),
        ],
        Field(
            description="Safety confirmation required for this file-writing operation; the export returns a failure message until set to true."
        ),
    ] = False,
):
    """Export a UniFi Protect recording clip as an MP4 file written to local disk.

    Mutating, file-writing operation: it resolves the camera (by id or name),
    fetches the recording for the requested time range, and writes an MP4 file
    into the server's confined export directory (the path is validated against
    that directory, so output_path must not escape it). Requires Protect
    username/password credentials configured for the console. The write is a
    no-op until confirm is set to true, at which point it returns the written
    file path and size in bytes. Use get_camera_snapshot for a single still image
    instead of a time-ranged clip.

    Args:
        camera: Protect camera identifier or name to export footage from.
        start_ts: Clip start time as a Unix epoch timestamp (seconds).
        end_ts: Clip end time as a Unix epoch timestamp (seconds); must be after
            start_ts.
        output_path: Destination filename (or path relative to the export
            directory); it is confined to the server's export directory.
        device: Optional Protect console name to target a specific UniFi Protect
            device; omit to use the first Protect-enabled device.
        confirm: Safety confirmation required for this file-writing operation;
            the export returns a failure message until set to true.
    """
    return await protect_tools.export_camera_clip(
        ctx, camera, start_ts, end_ts, output_path, device, confirm
    )


def _load_configured_plugins() -> PluginManager:
    core_tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}
    manager = PluginManager.load(
        discover_plugins(),
        allowlist=settings.allowed_plugins,
        required=settings.required_plugins,
        core_tool_names=core_tool_names,
    )
    for tool in manager.registry.tools.values():
        mcp.add_tool(
            tool.function,
            name=tool.name,
            description=tool.description,
            annotations=tool.annotations,
        )
        if scope_authorizer is not None:
            scope_authorizer.add_plugin_tool(tool.name, tool.scope)
    activate_plugins(manager)
    if scope_authorizer is not None:
        scope_authorizer.audit_tools(mcp._tool_manager.list_tools())
    return manager


plugin_manager = _load_configured_plugins()


if __name__ == "__main__":
    main()
