# ops/api.Dockerfile
# FastAPI / Dramatiq / APScheduler shared image.
# Build once; api, worker, scheduler services reuse it via image: intellibird-api:m1.

FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# Resolve deps first for better layer caching.
# dnstwist (Phase 12 / BRP-02) is pulled in via pyproject.toml dependencies and
# runs in-process inside the `worker` container on the brand-monitor queue.
# No docker.sock mount required (contrast Phase 11 BBOT easm-worker).
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --no-dev --locked --no-install-project

# Now copy application source.
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
RUN uv sync --no-dev --locked

# ---- Runtime ----
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        docker.io \
        libyara-dev \
        libpango-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser \
    # Match host docker socket group (gid 981 on the dev host) so easm-worker
    # can call /var/run/docker.sock without chmod 666. Override at build via
    # --build-arg DOCKER_HOST_GID=<your gid> if your host differs.
    && groupadd --gid 981 docker_host || true \
    && usermod -aG docker_host appuser

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1

USER appuser

# Default command (overridden by worker/scheduler services in compose)
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000"]
