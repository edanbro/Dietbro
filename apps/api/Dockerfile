# syntax=docker/dockerfile:1
# Build context: repo root (uv workspace). Two images from one file:
#   target `api` (default): the FastAPI app, also used by the one-shot `migrate` service.
#   target `worker`: the arq worker (apps/worker), the API's code plus OCR (rapidocr, onnxruntime,
#   opencv-headless and the bundled PP-OCR models). Only the worker reads receipt photos, so the
#   API image doesn't carry them.

FROM python:3.12-slim-trixie AS build-base
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# uv needs every workspace member's manifest to read the lockfile.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/
COPY packages/db/pyproject.toml packages/db/
COPY packages/data/pyproject.toml packages/data/
COPY packages/llm/pyproject.toml packages/llm/
COPY packages/solver/pyproject.toml packages/solver/


FROM build-base AS build-api
# Third-party deps first: this layer is reused until the lockfile or a manifest changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-api --no-install-workspace
COPY apps/api apps/api
COPY packages/core packages/core
COPY packages/db packages/db
COPY packages/llm packages/llm
COPY packages/solver packages/solver
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-api --no-editable


FROM build-base AS build-worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-worker --no-install-workspace
COPY apps/api apps/api
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/worker/src apps/worker/src
COPY packages/core packages/core
COPY packages/db packages/db
COPY packages/llm packages/llm
COPY packages/solver packages/solver
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package larder-worker --no-editable


FROM python:3.12-slim-trixie AS runtime
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1


FROM runtime AS worker
COPY --from=build-worker --chown=app:app /app/.venv /app/.venv
# No home directory for `app`; onnxruntime wants somewhere to write.
ENV HOME=/tmp
USER app
# Healthy while the worker writes its health key to Redis (every 30 s).
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD ["arq", "--check", "larder_worker.main.WorkerSettings"]
CMD ["arq", "larder_worker.main.WorkerSettings"]


FROM runtime AS api
COPY --from=build-api --chown=app:app /app/.venv /app/.venv
# For the one-shot `migrate` service: `alembic -c /app/alembic.ini upgrade head`.
COPY --chown=app:app packages/db/alembic.ini /app/alembic.ini
USER app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=10 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "larder_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
