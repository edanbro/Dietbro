# syntax=docker/dockerfile:1
# Build context: repo root (uv workspace). `docker compose build api`.

FROM python:3.12-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Third-party deps first: this layer is reused until the lockfile or a manifest changes.
# uv needs every workspace member's manifest to read the lockfile; only the API's deps install.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/core/pyproject.toml packages/core/
COPY packages/db/pyproject.toml packages/db/
COPY packages/data/pyproject.toml packages/data/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-api --no-install-workspace

COPY apps/api apps/api
COPY packages/core packages/core
COPY packages/db packages/db
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-api --no-editable


FROM python:3.12-slim-trixie AS runtime
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build --chown=app:app /app/.venv /app/.venv
# For the one-shot `migrate` service: `alembic -c /app/alembic.ini upgrade head`.
COPY --chown=app:app packages/db/alembic.ini /app/alembic.ini
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=10 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "larder_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
