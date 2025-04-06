#!/usr/bin/env bash
set -e

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
if ! command -v podman &> /dev/null; then
    echo "podman could not be found"
    exit
fi

podman build -t quay.io/jdanek/api-extension:latest -f ${SCRIPT_DIR}/Dockerfile ${SCRIPT_DIR}/
podman push quay.io/jdanek/api-extension:latest
kind load docker-image quay.io/jdanek/api-extension:latest
