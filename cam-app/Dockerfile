# Build stage: Install dependencies using UV
FROM python:3.11-slim-bullseye AS builder

# Build arguments for version information
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown

# Install UV for fast package installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /code

# Copy requirements file
COPY requirements.txt .

# Install dependencies using UV
RUN uv pip install --system --no-cache -r requirements.txt

# Runtime stage: Create minimal image
FROM python:3.11-slim-bullseye

# Build arguments for version information
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown

# Install FFmpeg (needed at runtime)
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set working directory
WORKDIR /code

# Copy application code
COPY ./app /code/app

# Create version.json with build metadata
RUN echo "{\"git_commit\": \"${GIT_COMMIT}\", \"git_branch\": \"${GIT_BRANCH}\", \"build_time\": \"${BUILD_TIME}\"}" > /code/app/version.json

CMD ["fastapi", "run", "app/main.py", "--port", "9090"]
