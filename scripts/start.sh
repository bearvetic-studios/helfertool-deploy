#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/deployment.sh"

python3 scripts/generate-config.py
mkdir -p -- "$STORAGE/data" "$STORAGE/log" "$STORAGE/postgres" "$STORAGE/rabbitmq"
"${COMPOSE[@]}" run --rm --no-deps permissions
"${COMPOSE[@]}" up -d
