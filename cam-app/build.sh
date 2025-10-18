#!/bin/bash

# Checks if local code is changed and rebuilds the image if needed.
# Usage: ./build.sh [now]
#   now - Force an immediate build before entering the watch loop

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

# Function to build the Docker image
build_image() {
    echo "Building Docker image..."

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
}

# If "now" argument is provided, build immediately
if [[ "$1" == "now" ]]; then
    echo "Forcing immediate build..."
    build_image
fi

while true; do
    echo "waiting for changes"
    inotifywait --recursive --event modify,create,delete \
        --exclude '.*\.jpg$' \
        "$DIRECTORY_TO_WATCH"

    echo "Change detected in directory '$DIRECTORY_TO_WATCH'."
    build_image

done
