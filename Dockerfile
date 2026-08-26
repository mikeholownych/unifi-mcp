FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml poetry.lock README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "unifi_mcp.server"]
