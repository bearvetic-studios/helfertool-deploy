#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
    echo "Missing .env; copy .env.example to .env and set real values." >&2
    exit 1
fi

python3 scripts/generate-config.py
mkdir -p storage/data storage/log storage/postgres storage/rabbitmq storage/run
docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" --env-file "$ROOT/.env" run --rm --no-deps permissions
docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" --env-file "$ROOT/.env" up -d
