# Base OS stage: System dependencies (cached independently)
FROM python:3.11-slim-bullseye AS base-os

# Install FFmpeg and other system dependencies
# This layer will be cached and reused unless the base image changes
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg \
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

# Install dependencies into system Python (no venv in container)
ENV UV_SYSTEM_PYTHON=1
RUN uv pip install --no-cache -r pyproject.toml && \
    uv pip install --no-cache ".[yolo]"

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

ENV YOLO_CONFIG_DIR=/tmp/Ultralytics

# Copy application code
COPY ./app /code/app

# Create version.json with build metadata
RUN echo "{\"git_commit\": \"${GIT_COMMIT}\", \"git_branch\": \"${GIT_BRANCH}\", \"build_time\": \"${BUILD_TIME}\"}" > /code/app/version.json

CMD ["fastapi", "run", "app/main.py", "--port", "9090"]
