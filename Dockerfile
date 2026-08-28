# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.14-slim AS runtime

RUN groupadd --gid 10001 unifi \
    && useradd --uid 10001 --gid unifi --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin unifi \
    && install -d --owner=unifi --group=unifi /app /data

WORKDIR /app

COPY --from=builder --chown=unifi:unifi /app/.venv /app/.venv

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

USER unifi

CMD ["python", "-m", "unifi_mcp.server"]
