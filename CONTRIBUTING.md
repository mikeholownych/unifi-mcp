# Contributing

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/mikeholownych/unifi-mcp.git
cd unifi-mcp
poetry install --with dev
cp .env.example .env   # fill in your controller details
```

## Development workflow

1. Create a feature branch from `main`
2. Make your changes
3. Run quality gates locally:

```bash
poetry run ruff check .
poetry run pytest -v
```

4. Open a pull request — CI runs the same gates.

## Guidelines

- **Style**: ruff with the configured rule set (line length 100, E501 ignored).
- **Tests**: new tools/features need coverage in `tests/`. Client behavior is
  tested with `respx` HTTP mocks; no real controller required.
- **Tool signatures**: every network tool should accept an optional
  `device: str | None` parameter and route it through `_get_client(ctx, device)`.
- **Read caching**: GET responses are cached ~15s per client instance. Mutating
  endpoints must never use the cache (they don't — only GET is cached) and
  should pass `_no_cache=True` when reading immediately after a write.
- **Secrets**: never commit `.env` or real credentials. CI fails on lint/test
  failures only — keep secrets out of fixtures too.
- **Commits**: short imperative subject lines; reference issues when applicable.

## Reporting bugs

Open an issue with: UniFi OS / Network application versions, MCP client
(Claude Desktop / Claude Code / opencode), the tool call made, expected vs
actual output, and relevant log lines (redact IPs/MACs as needed).
