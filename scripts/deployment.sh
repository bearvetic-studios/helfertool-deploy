#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
    echo "Missing .env; copy .env.example to .env first." >&2
    exit 1
fi

COMPOSE=(docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" -f "$ROOT/compose.bind-storage.yaml" --env-file "$ROOT/.env")
DEPLOYMENT_PATHS="$("${COMPOSE[@]}" config --format json | python3 -c '
import json
import sys
from pathlib import Path

config = json.load(sys.stdin)
root = Path(sys.argv[1]).resolve()

def mount(service, target):
    for volume in config["services"][service]["volumes"]:
        if volume["target"] == target and volume["type"] == "bind":
            return Path(volume["source"]).resolve()
    raise SystemExit(f"Missing bind mount for {service}: {target}")

storage = mount("helfertool", "/data").parent
if mount("postgres", "/var/lib/postgresql/data") != storage / "postgres" or mount("rabbitmq", "/var/lib/rabbitmq") != storage / "rabbitmq":
    raise SystemExit("Data services must use the same HELFERTOOL_STORAGE_PATH.")
if storage == root or storage in root.parents:
    raise SystemExit("HELFERTOOL_STORAGE_PATH must not contain the stack directory.")
backup = Path(config.get("x-backup-path") or "./backups")
if not backup.is_absolute():
    backup = root / backup
backup = backup.resolve()
if backup == storage or storage in backup.parents:
    raise SystemExit("HELFERTOOL_BACKUP_PATH must be outside HELFERTOOL_STORAGE_PATH.")
for path in (storage, backup):
    if "\n" in str(path) or "\r" in str(path):
        raise SystemExit("Deployment paths must not contain line breaks.")
    print(path)
' "$ROOT")"
mapfile -t DEPLOYMENT_PATHS <<< "$DEPLOYMENT_PATHS"
STORAGE="${DEPLOYMENT_PATHS[0]}"
BACKUP_DIR="${DEPLOYMENT_PATHS[1]}"