# Use the official Python 3.11 image as the base
FROM python:3.11-slim-bullseye

# Build arguments for version information
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown

# Install FFmpeg and other necessary tools
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    apscheduler \
    fastapi-login \
    fastapi-proxiedheadersmiddleware \
    fastapi[standard] \
    jinja2 \
    python-multipart \
    sqlalchemy \
    uvicorn[standard]

WORKDIR /code

COPY ./app /code/app

# Create version.json with build metadata
RUN echo "{\"git_commit\": \"${GIT_COMMIT}\", \"git_branch\": \"${GIT_BRANCH}\", \"build_time\": \"${BUILD_TIME}\"}" > /code/app/version.json

CMD ["fastapi", "run", "app/main.py", "--port", "9090"]
