#!/bin/bash

# Checks if local code is changed and rebuilds the image if needed.

DIRECTORY_TO_WATCH="/home/stream411/fieldcam/cam-app/app"

# Check if running on Linux
if [[ "$(uname)" != "Linux" ]]; then
    echo "This script is intended to run on Linux. Exiting."
    exit 1
fi

# Check if inotifywait is installed
if ! command -v inotifywait &> /dev/null; then
    echo "inotifywait is not installed. Please install it using your package manager."
    echo "For example, on Ubuntu or Debian: sudo apt-get install inotify-tools"
    exit 1
fi

while true; do
    echo "waiting for changes"
    inotifywait --recursive --event modify,create,delete \
        --exclude '.*\.jpg$' \
        "$DIRECTORY_TO_WATCH"

    echo "Change detected in directory '$DIRECTORY_TO_WATCH'."

    # Capture git information
    GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Build with version information
    docker build \
        --build-arg GIT_COMMIT="$GIT_COMMIT" \
        --build-arg GIT_BRANCH="$GIT_BRANCH" \
        --build-arg BUILD_TIME="$BUILD_TIME" \
        -t camapp .

    docker-compose up -d
    tput bel
    date

done
