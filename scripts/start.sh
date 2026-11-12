#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/deployment.sh"

mkdir -p -- "$STORAGE/config" "$STORAGE/data" "$STORAGE/log" "$STORAGE/postgres" "$STORAGE/rabbitmq"
"${COMPOSE[@]}" run --rm --no-deps permissions
"${COMPOSE[@]}" up -d
