#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AFTER_UPDATE_SCRIPT="$SCRIPT_DIR/afterUpdate.sh"

set -e

cd "$SCRIPT_DIR"

if [ ! -d ".git" ]; then
    exit 1
fi

if ! git diff-index --quiet HEAD --; then
    exit 1
fi

CURRENT_COMMIT=$(git rev-parse HEAD)

if ! git pull origin main; then
    echo "ERROR: Git pull fehlgeschlagen"
    exit 1
fi

NEW_COMMIT=$(git rev-parse HEAD)

if [ -f "$AFTER_UPDATE_SCRIPT" ]; then
    if [ -x "$AFTER_UPDATE_SCRIPT" ]; then
        "$AFTER_UPDATE_SCRIPT"
    else
        chmod +x "$AFTER_UPDATE_SCRIPT"
        "$AFTER_UPDATE_SCRIPT"
    fi
fi

exit 0
