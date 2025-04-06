#!/usr/bin/env bash
set -e

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
if ! command -v podman &> /dev/null; then
    echo "podman could not be found"
    exit
fi

podman build -t quay.io/jdanek/oauth-server:latest -f ${SCRIPT_DIR}/Dockerfile ${SCRIPT_DIR}/
podman push quay.io/jdanek/oauth-server:latest
kind load docker-image quay.io/jdanek/oauth-server:latest
