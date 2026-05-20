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

# Install dependencies into system Python (no venv in container).
# We intentionally install only the base dependencies and skip the optional
# `yolo` extra (`ultralytics` -> torch / CUDA / cuDNN), which roughly triples
# the image size and adds many minutes to the build. The app degrades
# gracefully when ultralytics is missing (see app/yolo_check.py). To build a
# YOLO-enabled image locally, change the line below to:
#   uv pip install --no-cache -r pyproject.toml --extra yolo
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

CMD ["fastapi", "run", "app/main.py", "--port", "9090"]
