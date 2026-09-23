# Single container, single process, single port.
#
# Dependencies are installed from the lockfile in their own layer, so editing
# a strategy rebuilds in about a second.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy mode plays nicely with bind mounts; bytecode compilation trades a
# slightly slower build for a faster start.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependency layer: only invalidated when the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application layer.
COPY polymarket ./polymarket

ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000

# No reason for the board to run as root.
RUN useradd --create-home --uid 1000 board && chown -R board:board /app
USER board

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\").read()"

CMD ["python", "polymarket/server.py"]
