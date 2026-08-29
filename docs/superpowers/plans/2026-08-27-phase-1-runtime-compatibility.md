# Phase 1 Runtime and MCP Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a clean, supported MCP runtime, preserve every existing tool contract, and add the disabled-by-default SQLite runtime foundation and server health endpoint required by later phases.

**Architecture:** Replace imports from the removed SDK v1 `mcp.server.fastmcp` module with MCP SDK 2's native `MCPServer` and injectable `mcp.server.mcpserver.Context`. Extend `AppContext` with an optional `RuntimeStore`; initialize it only when configured, and expose a pure health-summary function through one read-only MCP tool. Existing in-progress network changes remain untouched except where server contract tests must account for their registered tools.

**Tech Stack:** Python 3.11-3.14, MCP Python SDK 2.x, Pydantic Settings, aiosqlite, pytest, pytest-asyncio, Ruff, uv, Poetry

---

## File Structure

- Create `src/unifi_mcp/runtime/__init__.py`: public runtime exports.
- Create `src/unifi_mcp/runtime/store.py`: SQLite connection lifecycle, pragmas, and forward-only schema migration.
- Create `src/unifi_mcp/tools/system.py`: pure server-health projection used by the MCP wrapper.
- Create `src/unifi_mcp/version.py`: installed distribution version lookup with source-tree fallback.
- Create `tests/test_mcp_compat.py`: dependency, schema, annotation, and in-memory transport compatibility tests.
- Create `tests/test_runtime_store.py`: real temporary SQLite migration and lifecycle tests.
- Create `tests/test_system_tools.py`: redaction-safe health projection tests.
- Modify `pyproject.toml`: aligned PEP 621/Poetry dependencies and test matrix metadata.
- Modify `uv.lock` and `poetry.lock`: generated lock state for one project identity and one supported MCP stack.
- Modify `src/unifi_mcp/server.py`: MCPServer imports, version, system tool registration, and stdio startup.
- Modify `src/unifi_mcp/clients/base.py`: MCPServer lifespan typing plus optional runtime lifecycle.
- Modify `src/unifi_mcp/config.py`: disabled-by-default runtime settings and validated database path.
- Modify `src/unifi_mcp/__init__.py`: source the public version from one helper.
- Modify `tests/test_server.py`: inspect protocol tools through the in-memory client and use the supported lifespan path.
- Modify `.github/workflows/ci.yml`: test supported Python versions using uv and the canonical PEP 621 metadata.
- Modify `Dockerfile`: install from the canonical project metadata and run the supported entry point.
- Modify `README.md`, `.env.example`, and `CHANGELOG.md`: document runtime compatibility and optional persistence.

### Task 1: Lock the MCP Wire Contract Before Migration

**Files:**
- Create: `tests/test_mcp_compat.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add a failing import compatibility test**

```python
"""MCP runtime and wire-contract regression tests."""

import subprocess
import sys


def test_server_imports_with_supported_mcp_stack():
    result = subprocess.run(
        [sys.executable, "-c", "from unifi_mcp.server import mcp; print(mcp.name)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "UniFi MCP Server" in result.stdout
```

- [ ] **Step 2: Run the focused test and verify the current SDK mismatch fails**

Run: `uv run pytest tests/test_mcp_compat.py::test_server_imports_with_supported_mcp_stack -v`

Expected: FAIL because `mcp.server.fastmcp` is unavailable under MCP SDK 2.x.

- [ ] **Step 3: Record the existing public tool names and representative schemas**

Add a `EXPECTED_CORE_TOOLS` constant containing the stable tools documented in `README.md`, then add an async in-memory-client test:

```python
import pytest

EXPECTED_CORE_TOOLS = {
    "list_unifi_devices",
    "list_devices",
    "get_device_details",
    "list_clients",
    "get_client_details",
    "get_networks",
    "get_wlans",
    "get_firewall_policies",
    "analyze_network_issues",
    "list_cameras",
    "get_camera_snapshot",
    "get_global_inventory",
    "get_global_health",
    "get_global_client_summary",
}


@pytest.mark.asyncio
async def test_existing_tool_contract_is_preserved():
    from unifi_mcp.server import mcp

    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert EXPECTED_CORE_TOOLS <= tools.keys()
    list_devices = tools["list_devices"]
    assert set(list_devices.input_schema["properties"]) == {"site", "device"}
    assert list_devices.annotations.read_only_hint is True
    assert "ctx" not in list_devices.input_schema["properties"]
```

- [ ] **Step 4: Leave this test failing until Task 2 provides FastMCP**

Run: `uv run pytest tests/test_mcp_compat.py -v`

Expected: FAIL on the removed SDK v1 import.

### Task 2: Migrate to Native MCPServer on MCP SDK 2

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/unifi_mcp/server.py`
- Modify: `src/unifi_mcp/clients/base.py`
- Modify: `tests/test_server.py`
- Generate: `uv.lock`
- Generate: `poetry.lock`

- [ ] **Step 1: Align both dependency declarations**

Use the same constraints in `[project].dependencies` and `[tool.poetry.dependencies]`:

```toml
dependencies = [
    "mcp>=2.1,<3",
    "aiosqlite>=0.20,<1",
    "httpx>=0.28.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "tenacity>=8.0.0",
    "cachetools>=5.0.0",
]
```

```toml
[tool.poetry.dependencies]
python = ">=3.11"
mcp = ">=2.1,<3"
aiosqlite = ">=0.20,<1"
httpx = "^0.28.0"
pydantic = "^2.0"
pydantic-settings = "^2.0"
tenacity = ">=8.0.0"
cachetools = "^5.0.0"
```

- [ ] **Step 2: Replace removed FastMCP imports**

In `src/unifi_mcp/server.py` use:

```python
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
```

In `src/unifi_mcp/clients/base.py` use:

```python
from mcp.server.mcpserver import MCPServer
```

Instantiate `mcp = MCPServer(...)`. Keep all existing decorators, wrapper signatures, and the stdio `mcp.run()` call unchanged.

- [ ] **Step 3: Adapt server tests to native protocol tool models**

Use native `await mcp.list_tools()` results and their Python field names:

```python
async def list_protocol_tools():
    return await mcp.list_tools()
```

Use `tool.input_schema` and annotation fields such as `read_only_hint`. Verify wire aliases with `tool.model_dump(by_alias=True)` where needed. Replace direct access to `mcp.settings.lifespan` by invoking `create_app_lifespan(mcp)` directly while patching `unifi_mcp.clients.base.settings` to the desired test settings.

- [ ] **Step 4: Regenerate both lock files without editing them manually**

Run: `uv lock`

Run: `poetry lock`

Expected: one editable project named `mcp-unifi`; MCP SDK 2.x satisfies both lock solvers.

- [ ] **Step 5: Verify the MCP migration tests pass**

Run: `uv sync --all-extras && uv run pytest tests/test_mcp_compat.py tests/test_server.py -v`

Expected: PASS; context parameters are absent from wire schemas and annotations remain present.

### Task 3: Centralize Version Metadata

**Files:**
- Create: `src/unifi_mcp/version.py`
- Modify: `src/unifi_mcp/__init__.py`
- Modify: `src/unifi_mcp/server.py`
- Test: `tests/test_system_tools.py`

- [ ] **Step 1: Write failing version tests**

```python
from unittest.mock import patch

from unifi_mcp.version import get_version


def test_get_version_uses_distribution_metadata():
    with patch("unifi_mcp.version.version", return_value="9.8.7"):
        assert get_version() == "9.8.7"


def test_get_version_has_source_tree_fallback():
    from importlib.metadata import PackageNotFoundError

    with patch("unifi_mcp.version.version", side_effect=PackageNotFoundError):
        assert get_version() == "0+unknown"
```

- [ ] **Step 2: Verify the module is missing**

Run: `uv run pytest tests/test_system_tools.py -v`

Expected: collection ERROR because `unifi_mcp.version` does not exist.

- [ ] **Step 3: Implement one version source**

```python
"""Package version helpers."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed distribution version."""
    try:
        return version("mcp-unifi")
    except PackageNotFoundError:
        return "0+unknown"
```

Update `src/unifi_mcp/__init__.py`:

```python
"""UniFi MCP Server - MCP integration for UniFi Network and Protect APIs."""

from unifi_mcp.version import get_version

__version__ = get_version()
```

Pass `version=get_version()` to `MCPServer(...)` in `server.py`.

- [ ] **Step 4: Verify version tests pass**

Run: `uv run pytest tests/test_system_tools.py -v`

Expected: PASS.

### Task 4: Add the Optional SQLite Runtime Store

**Files:**
- Create: `src/unifi_mcp/runtime/__init__.py`
- Create: `src/unifi_mcp/runtime/store.py`
- Create: `tests/test_runtime_store.py`

- [ ] **Step 1: Write failing migration and lifecycle tests**

```python
import pytest

from unifi_mcp.runtime.store import SCHEMA_VERSION, RuntimeStore


@pytest.mark.asyncio
async def test_initialize_creates_runtime_schema(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    try:
        health = await store.health()
    finally:
        await store.close()

    assert health == {
        "connected": True,
        "schema_version": SCHEMA_VERSION,
        "journal_mode": "wal",
    }


@pytest.mark.asyncio
async def test_open_is_idempotent_and_close_marks_disconnected(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    await store.open()
    await store.close()

    assert store.connected is False
```

- [ ] **Step 2: Verify runtime modules are missing**

Run: `uv run pytest tests/test_runtime_store.py -v`

Expected: collection ERROR because `unifi_mcp.runtime` does not exist.

- [ ] **Step 3: Implement the initial forward-only migration**

`src/unifi_mcp/runtime/store.py` must define `SCHEMA_VERSION = 1`, own one `aiosqlite.Connection`, serialize open/close with an `asyncio.Lock`, create parent directories, and execute:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Insert migration version `1` with `datetime.now(timezone.utc).isoformat()`. Reject a database whose maximum migration version is greater than `SCHEMA_VERSION` with `UniFiConfigError`.

Export `RuntimeStore` and `SCHEMA_VERSION` from `src/unifi_mcp/runtime/__init__.py`.

- [ ] **Step 4: Verify runtime tests pass**

Run: `uv run pytest tests/test_runtime_store.py -v`

Expected: PASS with a real temporary SQLite database.

### Task 5: Configure and Manage Runtime Lifespan

**Files:**
- Modify: `src/unifi_mcp/config.py`
- Modify: `src/unifi_mcp/clients/base.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`
- Test: `tests/test_runtime_store.py`

- [ ] **Step 1: Write failing runtime-setting tests**

```python
def test_runtime_is_disabled_by_default(tmp_path):
    settings = UniFiSettings(_env_file=None, data_dir=tmp_path)
    assert settings.runtime_enabled is False
    assert settings.runtime_database_path == tmp_path / "runtime.db"


def test_runtime_database_override_is_resolved(tmp_path):
    database = tmp_path / "custom.db"
    settings = UniFiSettings(
        _env_file=None,
        runtime_enabled=True,
        runtime_database=database,
    )
    assert settings.runtime_database_path == database
```

- [ ] **Step 2: Verify settings do not exist yet**

Run: `uv run pytest tests/test_config.py -v`

Expected: FAIL with missing `runtime_enabled` or `runtime_database_path`.

- [ ] **Step 3: Add runtime settings**

Add to `UniFiSettings`:

```python
runtime_enabled: bool = Field(default=False)
data_dir: Path = Field(
    default_factory=lambda: (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "unifi-mcp"
    )
)
runtime_database: Path | None = Field(default=None)


@property
def runtime_database_path(self) -> Path:
    return self.runtime_database or self.data_dir / "runtime.db"
```

Import `os` and retain `Path`. Document `UNIFI_RUNTIME_ENABLED`, `UNIFI_DATA_DIR`, and `UNIFI_RUNTIME_DATABASE` in `.env.example` with persistence disabled.

- [ ] **Step 4: Add the optional store to `AppContext` and lifespan**

Extend `AppContext`:

```python
runtime: RuntimeStore | None = field(default=None)
```

In `create_app_lifespan`, instantiate and open `RuntimeStore(settings.runtime_database_path)` only when `settings.runtime_enabled` is true. Pass it into `AppContext` and close it in `finally` before closing the HTTP client. If opening fails, close the HTTP client and fail startup with the original actionable error.

- [ ] **Step 5: Verify disabled and enabled lifecycle behavior**

Add tests using temporary paths and `create_app_lifespan(mcp)`, then run:

Run: `uv run pytest tests/test_config.py tests/test_runtime_store.py tests/test_server.py -v`

Expected: PASS; disabled runtime creates no database and enabled runtime closes cleanly.

### Task 6: Add a Redaction-Safe Server Health Tool

**Files:**
- Create: `src/unifi_mcp/tools/system.py`
- Modify: `src/unifi_mcp/server.py`
- Modify: `tests/test_system_tools.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing pure health-summary tests**

```python
from unifi_mcp.tools.system import build_server_health


@pytest.mark.asyncio
async def test_health_reports_services_without_secrets(mock_ctx):
    health = await build_server_health(mock_ctx)

    assert health["status"] == "ok"
    assert health["transport"] == "stdio"
    assert health["configured_devices"] == 1
    assert health["services"] == {"network": 1, "protect": 0}
    assert health["persistence"] == {"enabled": False, "connected": False}
    rendered = repr(health)
    assert "test-key" not in rendered
    assert "10.0.0.1" not in rendered
```

- [ ] **Step 2: Verify the health module is missing**

Run: `uv run pytest tests/test_system_tools.py -v`

Expected: collection ERROR because `unifi_mcp.tools.system` does not exist.

- [ ] **Step 3: Implement the pure health projection**

`build_server_health(ctx: AppContext) -> dict[str, Any]` returns version, status, transport, configured device count, service counts, and persistence state. When a runtime store exists, merge `await ctx.runtime.health()` into `persistence`; never include controller URLs, device names, API keys, usernames, database paths, or environment values.

- [ ] **Step 4: Register the MCP wrapper**

In `server.py`:

```python
from unifi_mcp.tools import system as system_tools


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_server_health(ctx: Context):
    """Get redaction-safe UniFi MCP runtime health and capability counts."""
    return await system_tools.build_server_health(ctx.request_context.lifespan_context)
```

- [ ] **Step 5: Verify protocol registration and output**

Add `get_server_health` to the registration tests and run:

Run: `uv run pytest tests/test_system_tools.py tests/test_mcp_compat.py tests/test_server.py -v`

Expected: PASS; the tool has `readOnlyHint=true` and no input properties.

### Task 7: Update CI, Container, and User Documentation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Dockerfile`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Expand CI to the supported Python matrix**

Use `actions/setup-python@v5` with:

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.12", "3.13", "3.14"]
```

Install uv with `astral-sh/setup-uv@v6`, run `uv sync --locked --all-extras`, then run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest -v`. This makes PEP 621 metadata canonical in CI while Poetry remains validated by lock generation.

- [ ] **Step 2: Keep the container on the canonical entry point**

Retain `python -m unifi_mcp.server`, but update the image build to copy `uv.lock`, install with `uv sync --locked --no-dev`, and run from the project virtual environment. Do not enable persistence or expose a network port by default.

- [ ] **Step 3: Document compatibility and persistence**

Update README installation and configuration sections to state:

- The server runs on MCP SDK 2's native `MCPServer` API.
- Stdio remains the default transport.
- Runtime persistence is disabled by default.
- Enabling it creates `runtime.db` under `UNIFI_DATA_DIR` unless `UNIFI_RUNTIME_DATABASE` is set.
- The health tool never returns credentials, controller addresses, or database paths.

Add an Unreleased changelog section listing the runtime migration, package-identity cleanup, optional SQLite foundation, and `get_server_health`.

- [ ] **Step 4: Run documentation and formatting checks**

Run: `uv run ruff format --check . && uv run ruff check .`

Expected: PASS.

### Task 8: Full Phase 1 Verification

**Files:**
- Verify all Phase 1 files

- [ ] **Step 1: Verify dependency consistency**

Run: `uv lock --check`

Run: `poetry check --lock`

Expected: both pass and identify the project as `mcp-unifi` only.

- [ ] **Step 2: Run the complete test suite**

Run: `uv run pytest -v`

Expected: all tests pass with no unclosed-client or coroutine warnings.

- [ ] **Step 3: Run static quality checks**

Run: `uv run ruff format --check .`

Run: `uv run ruff check .`

Expected: both pass.

- [ ] **Step 4: Smoke-test package and server startup**

Run: `uv build`

Expected: wheel and source distribution build as `mcp_unifi` version matching `pyproject.toml`.

Run: `timeout 3 uv run unifi-mcp`

Expected: server initializes over stdio and exits only because `timeout` ends the process; no import error appears.

- [ ] **Step 5: Inspect only intended changes**

Run: `git status --short`

Run: `git diff --check`

Expected: Phase 1 files plus the pre-existing uncommitted network-tool files are present; no existing unrelated change has been reverted or overwritten.

Do not commit unless the user explicitly requests it.
