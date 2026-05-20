#!/bin/bash

cd cam-app

docker build \
    --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
    --build-arg GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)" \
    --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -t ghcr.io/jkrauska/fieldcam/camapp:latest \
    . \
&& docker push ghcr.io/jkrauska/fieldcam/camapp:latest


