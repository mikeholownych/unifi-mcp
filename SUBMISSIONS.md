# Submission Materials

All materials are ready. server.json has been validated against the Official MCP Registry.

## Quick start — what to do now

### Step 1: Glama (do first — awesome-mcp-servers requires it)

Go to https://glama.ai/mcp/servers and submit:
- **Repository URL**: https://github.com/mikeholownych/unifi-mcp
- **Name**: UniFi MCP Server
- **Description**: MCP server for Ubiquiti UniFi Network and Protect. 63 tools for device management, client monitoring, VLAN/firewall configuration, WiFi optimization, camera snapshots, multi-site orchestration. 16 agent skills.
- **Category**: Networking / Smart Home
- **Transport**: stdio
- **Runtime**: Python

### Step 2: awesome-mcp-servers PR

Fork https://github.com/punkpeye/awesome-mcp-servers, then add this entry under the appropriate category:

```markdown
- [UniFi MCP](https://github.com/mikeholownych/unifi-mcp): MCP server for Ubiquiti UniFi Network and Protect — 63 tools for device management, client monitoring, VLAN/firewall, WiFi optimization, cameras, multi-site orchestration. 16 agent skills. Install: `pip install unifi-mcp`. ![PyPI](https://img.shields.io/pypi/v/unifi-mcp)
```

PR title: `Add UniFi MCP server`
PR body:
```
Adds the UniFi MCP server — comprehensive MCP implementation for Ubiquiti UniFi infrastructure.

Features:
- 63 tools across network and Protect APIs
- 16 bundled agent skills for guided workflows
- Multi-device/multi-site support
- Zone-based firewall management (Network 9+/10)
- Camera snapshots and event monitoring

Glama listing: [link after Step 1]
```

### Step 3: Official MCP Registry

```bash
# Install the publisher CLI (one-time)
curl -sL "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_linux_amd64.tar.gz" | tar xz mcp-publisher
chmod +x mcp-publisher

# Authenticate (requires GitHub account with public membership in mikeholownych)
./mcp-publisher login github

# Publish (from repo root where server.json lives)
./mcp-publisher publish

# Verify
curl "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.mikeholownych/unifi-mcp"
```

### Step 4: Other directories (optional, ~10 min total)

| Directory | URL | Action |
|-----------|-----|--------|
| Smithery | https://smithery.ai/publish | Submit repo URL, categories: Networking, Smart Home |
| MCPfind | https://mcpfind.org | Submit GitHub URL |
| MCP.so | https://mcp.so | Submit with GitHub login |
| MCP Directory | https://mcp.directory | Auto-pulls from GitHub |

### Step 5: Community posts

- **Reddit r/Ubiquiti**: Show-and-tell post with feature list
- **Reddit r/selfhosted**: Self-hosted angle
- **Ubiquiti Community Forums**: Brief post with GitHub link

## What's included

| File | Purpose |
|------|---------|
| `server.json` | Official MCP Registry metadata (validated ✅) |
| `.github/workflows/mcp-registry.yml` | Auto-publish on GitHub Release |
| `.github/workflows/release.yml` | PyPI publish on tag |
| `SUBMISSIONS.md` | This file — step-by-step guide |

## Timeline

| Step | Time | Visibility |
|------|------|------------|
| Glama | ~5 min submit | Verified badge, awesome-mcp-servers prerequisite |
| awesome-mcp-servers | PR merge ~1-3 days | 83K+ stars, highest visibility |
| Official Registry | Immediate after auth | Canonical source, all clients ingest |
| PulseMCP | ~7 days auto | Aggregator, no action needed |
| Smithery | ~3-14 days | 7,300+ servers |
| Reddit posts | Immediate | Community awareness |
