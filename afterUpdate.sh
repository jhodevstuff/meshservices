#!/bin/bash

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [afterUpdate] $1"
}

log "afterUpdate.sh wird ausgeführt..."

sudo systemctl restart meshservices

log "afterUpdate.sh abgeschlossen"

exit 0
