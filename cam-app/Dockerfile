# Base OS stage: System dependencies (cached independently)
FROM python:3.11-slim-bullseye AS base-os

# Install FFmpeg and other system dependencies
# This layer will be cached and reused unless the base image changes
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg iputils-ping procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install UV for fast package installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/


# Python environment stage: Install Python dependencies using UV
FROM base-os AS python-env

# Set working directory
WORKDIR /code

# Copy dependency manifest (rebuilt when pyproject.toml changes)
COPY pyproject.toml .

# Install runtime dependencies into system Python (no venv in container).
# YOLO detection runs on onnxruntime (a base dependency) against the ONNX model
# baked in below — torch / ultralytics are NOT installed here (export-only, see
# pyproject.toml). This stage rebuilds only when pyproject.toml changes.
ENV UV_SYSTEM_PYTHON=1
RUN uv pip install --no-cache -r pyproject.toml

# Runtime stage: Create minimal image
FROM base-os

# Build arguments for version information
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown

# Copy installed Python packages from python-env stage
# Rebuilds when pyproject.toml changes
COPY --from=python-env /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=python-env /usr/local/bin /usr/local/bin

# Set working directory
WORKDIR /code

# Copy application code
COPY ./app /code/app

# Create version.json with build metadata
RUN echo "{\"git_commit\": \"${GIT_COMMIT}\", \"git_branch\": \"${GIT_BRANCH}\", \"build_time\": \"${BUILD_TIME}\"}" > /code/app/version.json

# Deployment notes:
#   The in-app settings page (/settings/save) writes to /code/.env and then
#   sends SIGTERM to itself so the new values are picked up on next boot.
#   For that to work in production this container must be run with:
#     1. A restart policy, e.g. `docker run --restart=unless-stopped ...`
#        or compose `restart: unless-stopped`. Without it, saving settings
#        will simply stop the container.
#     2. The .env file bind-mounted from the host so changes survive
#        container recreation, e.g. `-v /host/path/.env:/code/.env`
#        (compose: `volumes: ["./cam-app/.env:/code/.env"]`).
#   If .env is not mounted, settings can still be edited but are lost on the
#   next image rebuild / `docker compose up --force-recreate`.
#
#   The startup config dump (sensitive values redacted) is suppressed by
#   default. To enable it for troubleshooting, run the container with
#   `-e DEBUG=1` (or set DEBUG=1 in the bind-mounted .env).
#
#   YOLO detection runs on onnxruntime against app/models/yolov8n.onnx (baked
#   into the image via `COPY ./app`), so there is no torch and no runtime model
#   download. Keep runtime-written data (captures, logs) on a mounted volume so
#   it doesn't bloat the container's writable layer.
CMD ["fastapi", "run", "app/main.py", "--port", "9090"]
