#!/usr/bin/env python3
"""Inject Annotated[..., Field(description=...)] into server.py tool wrappers using Args: from docstrings."""

import ast
import re
import sys
from pathlib import Path

SERVER_PY = Path("/tmp/opencode/Unifi-mcp-phase1/worktree/src/unifi_mcp/server.py")

TARGET_FUNCS = frozenset("""get_server_health get_plugin_status get_snapshot_capabilities export_portable_snapshot verify_snapshot export_network_report capture_observations_now query_observation_trends list_observation_scopes get_observation_retention_status get_client_organization set_client_tags create_client_group delete_client_group assign_client_group list_client_groups list_clients_by_organization get_client_qos_capabilities plan_client_qos_policy apply_client_qos_policy list_runtime_events get_event_polling_status poll_events_now list_schedules create_interval_schedule set_schedule_enabled delete_schedule run_schedule_now list_job_runs list_webhook_destinations create_webhook_destination set_webhook_destination_enabled delete_webhook_destination test_webhook_destination list_webhook_deliveries list_devices get_device_details restart_device locate_device get_device_stats upgrade_device provision_device get_device_ports set_device_port list_clients list_all_clients get_client_details block_client unblock_client kick_client forget_client get_client_traffic reserve_client_ip list_sites get_site_health get_site_settings get_sysinfo get_networks create_network update_network delete_network get_wlans get_port_profiles get_firewall_rules get_firewall_policies update_wlan create_wlan delete_wlan create_firewall_policy set_firewall_policy_enabled delete_firewall_policy get_port_forwards create_port_forward delete_port_forward get_all_sites_health get_routing_table get_network_health get_recent_events get_alarms archive_all_alarms run_speed_test get_speed_test_status get_dpi_stats get_traffic_summary analyze_network_issues get_optimization_recommendations get_client_experience_report get_device_health_summary get_traffic_analysis troubleshoot_client list_cameras get_camera_details get_camera_snapshot get_protect_system_info get_camera_health_summary get_liveviews get_protect_accessories get_motion_events get_smart_detections get_protect_event_summary get_recent_protect_activity list_unifi_devices get_global_inventory get_global_health get_global_client_summary export_camera_clip""".split())

def parse_args_section(docstring: str) -> dict[str, str]:
    """Extract Args: block -> {param: description}. Collapses multi-line descriptions."""
    if not docstring:
        return {}
    lines = docstring.splitlines()
    # Find Args: line
    args_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Args:"):
            args_start = i
            break
    if args_start is None:
        return {}
    params = {}
    current_param = None
    current_desc_lines = []
    for line in lines[args_start + 1 :]:
        stripped = line.strip()
        # Stop at next section (Returns:, Yields:, Raises:, Examples:, Note:, blank at indent 0 after content)
        if re.match(r"^(Returns|Yields|Raises|Examples?|Note):", stripped):
            if current_param:
                params[current_param] = " ".join(current_desc_lines).strip()
            break
        # New param: exactly 4-space indent, name: desc
        m = re.match(r"^    ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            if current_param:
                params[current_param] = " ".join(current_desc_lines).strip()
            current_param = m.group(1)
            current_desc_lines = [m.group(2)] if m.group(2) else []
        elif current_param is not None and line.startswith("        "):
            # Continuation (8+ spaces)
            current_desc_lines.append(stripped)
        elif current_param is not None and not line.strip():
            # blank line - end of Args
            params[current_param] = " ".join(current_desc_lines).strip()
            break
    if current_param and current_param not in params:
        params[current_param] = " ".join(current_desc_lines).strip()
    return params

def escape_for_field(desc: str) -> str:
    """Escape for Field(description="...") using double quotes, escape backslash and quote."""
    return desc.replace("\\", "\\\\").replace('"', '\\"')

def build_annotated(ann: ast.AST | None, default: ast.AST | None, desc: str) -> str:
    """Build string: Annotated[<ann>, Field(description="<escaped>")] [= <default>]."""
    ann_str = ast.unparse(ann) if ann else "Any"
    default_str = f" = {ast.unparse(default)}" if default else ""
    field_desc = escape_for_field(desc)
    return f"Annotated[{ann_str}, Field(description=\"{field_desc}\")]{default_str}"

def main():
    src = SERVER_PY.read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)  # keep newlines for reconstruction

    # Map function name -> (node, args_descriptions)
    func_data = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in TARGET_FUNCS:
            doc = ast.get_docstring(node) or ""
            args_desc = parse_args_section(doc)
            if args_desc:
                func_data[node.name] = (node, args_desc)

    # For each target, replace its signature line(s)
    # We'll build a new source by processing lines with replacements.
    # Easier: for each func, find the signature span in original source, replace it.
    # We'll do replacements from bottom to top (higher line numbers first) to keep line numbers stable.
    
    replacements = []  # list of (start_line_idx, end_line_idx_excl, new_header_lines)
    for name, (node, args_desc) in func_data.items():
        # Find the def header span: from node.lineno to the line containing the closing ':' at depth 0
        start_idx = node.lineno - 1  # 0-based
        # Scan lines to find def end
        depth_paren = 0
        depth_bracket = 0
        def_end_idx = None
        for i in range(start_idx, len(lines)):
            line = lines[i]
            # Track depths
            for ch in line:
                if ch == '(':
                    depth_paren += 1
                elif ch == ')':
                    depth_paren -= 1
                elif ch == '[':
                    depth_bracket += 1
                elif ch == ']':
                    depth_bracket -= 1
                elif ch == ':' and depth_paren == 0 and depth_bracket == 0:
                    # This is the def closing colon (first at depth 0 after def start)
                    def_end_idx = i
                    break
            if def_end_idx is not None:
                break
        if def_end_idx is None:
            print(f"WARNING: Could not find def end for {name}", file=sys.stderr)
            continue

        # Build new signature
        # Get annotations and defaults
        args = node.args
        # Collect all positional/keyword args (including *args, **kwargs if any - unlikely)
        all_params = []
        all_params.extend(args.posonlyargs)
        all_params.extend(args.args)
        all_params.extend(args.kwonlyargs)
        if args.vararg:
            all_params.append(args.vararg)
        if args.kwarg:
            all_params.append(args.kwarg)
        
        # Defaults: args.defaults corresponds to last N positional args; args.kw_defaults to kwonlyargs
        # Map param name -> (annotation, default_ast_or_None)
        defaults_map = {}
        # positional defaults
        num_pos = len(args.posonlyargs) + len(args.args)
        pos_defaults = args.defaults
        for i, arg in enumerate(args.posonlyargs + args.args):
            if i >= num_pos - len(pos_defaults):
                defaults_map[arg.arg] = pos_defaults[i - (num_pos - len(pos_defaults))]
            else:
                defaults_map[arg.arg] = None
        # kwonly defaults
        for i, arg in enumerate(args.kwonlyargs):
            defaults_map[arg.arg] = args.kw_defaults[i] if args.kw_defaults[i] is not None else None
        if args.vararg:
            defaults_map[args.vararg.arg] = None
        if args.kwarg:
            defaults_map[args.kwarg.arg] = None

        # Build new param strings
        new_params = []
        for param in all_params:
            pname = param.arg
            pann = param.annotation
            pdefault = defaults_map.get(pname)
            if pname == "ctx":
                # Keep ctx unchanged
                ann_str = ast.unparse(pann) if pann else "Context"
                default_str = f" = {ast.unparse(pdefault)}" if pdefault else ""
                new_params.append(f"{pname}: {ann_str}{default_str}")
            else:
                desc = args_desc.get(pname)
                if desc is None:
                    # Should not happen, but fallback: no Annotated
                    ann_str = ast.unparse(pann) if pann else "Any"
                    default_str = f" = {ast.unparse(pdefault)}" if pdefault else ""
                    new_params.append(f"{pname}: {ann_str}{default_str}")
                else:
                    ann_str = build_annotated(pann, pdefault, desc)
                    new_params.append(f"{pname}: {ann_str}")

        # Return annotation
        ret_ann = node.returns
        ret_str = f" -> {ast.unparse(ret_ann)}" if ret_ann else ""

        # Build new header
        header = f"async def {name}({', '.join(new_params)}){ret_str}:"
        
        # Replacement span: lines[start_idx : def_end_idx+1] (inclusive of def_end_idx line)
        # We'll replace that entire span with the single-line header + the original docstring line and body
        # But careful: the docstring and body start AFTER the def_end_idx line.
        # The original header lines may include the docstring start on same line? No, def ends with :, next line is docstring or body.
        # So we replace lines[start_idx : def_end_idx+1] with [header + "\n"]
        replacements.append((start_idx, def_end_idx + 1, [header + "\n"]))

    # Apply replacements in reverse order (highest start_idx first)
    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, new_lines in replacements:
        lines[start:end] = new_lines

    # Now ensure imports: Annotated from typing, Field from pydantic
    # Find where to insert: after existing typing imports
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and line.strip().startswith("from typing import"):
            # Insert Annotated if not present
            if "Annotated" not in line:
                # Modify this line to include Annotated
                new_lines[-1] = line.rstrip() + ", Annotated\n"
            inserted = True
        elif not inserted and line.strip() == "from typing import Any":
            # Replace with both
            new_lines[-1] = "from typing import Any, Annotated\n"
            inserted = True
        elif not inserted and line.strip().startswith("import ") or line.strip().startswith("from "):
            # If we pass the import block, add before next non-import
            pass
    
    # Also ensure Field import from pydantic
    has_field_import = any("from pydantic import" in l and "Field" in l for l in new_lines)
    if not has_field_import:
        # Add after typing import block
        for i, line in enumerate(new_lines):
            if line.strip().startswith("from typing import") or line.strip().startswith("import typing"):
                new_lines.insert(i + 1, "from pydantic import Field\n")
                break

    new_src = "".join(new_lines)
    # Verify syntax
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"SYNTAX ERROR after transform: {e}", file=sys.stderr)
        sys.exit(1)

    SERVER_PY.write_text(new_src)
    print(f"Updated {SERVER_PY}")
    print(f"Processed {len(replacements)} functions")

if __name__ == "__main__":
    main()