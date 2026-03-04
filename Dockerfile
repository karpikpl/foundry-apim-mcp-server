# ── Build stage ──────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen --no-install-project

COPY foundry_apim_mcp_server/ foundry_apim_mcp_server/
RUN uv sync --no-dev --frozen

# ── Runtime stage ────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["foundry-mcp-server"]
