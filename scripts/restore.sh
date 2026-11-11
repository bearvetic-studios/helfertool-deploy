#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 backup-file.tar.gz" >&2
    exit 2
fi

ARCHIVE="$(realpath -- "$1")"
source "$(dirname -- "${BASH_SOURCE[0]}")/deployment.sh"
umask 077
mkdir -p -- "$STORAGE"
printf 'Restore %s and replace the current data, PostgreSQL and RabbitMQ state? Type RESTORE to continue: ' "$ARCHIVE"
read -r CONFIRMATION
if [[ "$CONFIRMATION" != RESTORE ]]; then
    echo "Restore cancelled."
    exit 1
fi

STAGING="$(mktemp -d "$ROOT/.restore.XXXXXX")"
STORAGE_STAGING=""
SERVICES_STOPPED=false
RESTORE_COMPLETE=false
declare -A OLD_MOVED=()
declare -A NEW_MOVED=()
CONFIG_OLD_MOVED=false
CONFIG_NEW_MOVED=false
cleanup() {
    local cleanup_failed=false
    if [[ "$RESTORE_COMPLETE" != true ]]; then
        if [[ "$CONFIG_NEW_MOVED" == true && -e "$ROOT/config" ]]; then
            rm -rf -- "$ROOT/config" || cleanup_failed=true
        fi
        if [[ "$CONFIG_OLD_MOVED" == true ]]; then
            mv -- "$STAGING/previous/config" "$ROOT/config" || cleanup_failed=true
        fi
        for service in rabbitmq postgres data; do
            if [[ "${NEW_MOVED[$service]:-false}" == true && -e "$STORAGE/$service" ]]; then
                rm -rf -- "$STORAGE/$service" || cleanup_failed=true
            fi
            if [[ "${OLD_MOVED[$service]:-false}" == true ]]; then
                mv -- "$STORAGE_STAGING/old-$service" "$STORAGE/$service" || cleanup_failed=true
            fi
        done
    fi
    if [[ "$SERVICES_STOPPED" == true ]]; then
        if ! "${COMPOSE[@]}" up -d postgres rabbitmq helfertool >/dev/null; then
            echo "Could not restart the Compose services; inspect them with docker compose ps." >&2
            cleanup_failed=true
        fi
    fi
    if [[ "$RESTORE_COMPLETE" == true || "$cleanup_failed" == false ]]; then
        if [[ -n "$STORAGE_STAGING" ]]; then
            rm -rf -- "$STORAGE_STAGING" || cleanup_failed=true
        fi
        rm -rf -- "$STAGING" || cleanup_failed=true
    else
        echo "Restore rollback was incomplete; preserve recovery files at $STAGING and $STORAGE_STAGING." >&2
    fi
}
trap cleanup EXIT

python3 - "$ARCHIVE" "$STAGING" <<'PY'
import os
import sys
import tarfile
from pathlib import Path

archive_path, destination = sys.argv[1:]
allowed = {
    "config/helfertool.yaml",
    "storage/data",
    "storage/postgres",
    "storage/rabbitmq",
}
seen_roots = set()

with tarfile.open(archive_path, "r:gz") as archive:
    members = archive.getmembers()
    for member in members:
        name = member.name.rstrip("/")
        parts = name.split("/")
        if name.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise SystemExit(f"Unsafe archive path: {member.name}")
        if parts[0] == "config":
            valid = (name == "config" and member.isdir()) or (name in ("config/helfertool.yaml", "config/deployment.env") and member.isfile())
            root = "config/helfertool.yaml" if name == "config/helfertool.yaml" else ""
        elif parts[0] == "storage" and len(parts) >= 2 and parts[1] in ("data", "postgres", "rabbitmq"):
            valid = (name in ("storage/data", "storage/postgres", "storage/rabbitmq") and member.isdir()) or len(parts) > 2
            root = "storage/" + parts[1]
        else:
            valid = False
            root = ""
        if not valid or not (member.isdir() or member.isfile()):
            raise SystemExit(f"Unexpected archive entry: {member.name}")
        if root:
            seen_roots.add(root)
    if seen_roots != allowed:
        raise SystemExit("Archive must contain the Helfertool config, data, PostgreSQL and RabbitMQ directories.")

    for member in members:
        name = member.name.rstrip("/")
        target = Path(destination, *name.split("/"))
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            os.chmod(target, member.mode & 0o777)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"Could not read archive entry: {member.name}")
            with source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            os.chmod(target, 0o600 if name.startswith("config/") else member.mode & 0o777)
        if os.geteuid() == 0:
            os.chown(target, member.uid, member.gid)
PY

STORAGE_STAGING="$(mktemp -d "$STORAGE/.restore.XXXXXX")"
for service in data postgres rabbitmq; do
    cp -a -- "$STAGING/storage/$service" "$STORAGE_STAGING/new-$service"
done

SERVICES_STOPPED=true
"${COMPOSE[@]}" stop helfertool postgres rabbitmq

mkdir -p "$STAGING/previous"
for service in data postgres rabbitmq; do
    if [[ -e "$STORAGE/$service" ]]; then
        mv -- "$STORAGE/$service" "$STORAGE_STAGING/old-$service"
        OLD_MOVED[$service]=true
    fi
    mv -- "$STORAGE_STAGING/new-$service" "$STORAGE/$service"
    NEW_MOVED[$service]=true
done
if [[ -e "$ROOT/config" ]]; then
    mv -- "$ROOT/config" "$STAGING/previous/config"
    CONFIG_OLD_MOVED=true
fi
mv -- "$STAGING/config" "$ROOT/config"
CONFIG_NEW_MOVED=true

"${COMPOSE[@]}" run --rm --no-deps permissions
"${COMPOSE[@]}" up -d postgres rabbitmq
"${COMPOSE[@]}" up -d helfertool
RESTORE_COMPLETE=true
SERVICES_STOPPED=false
echo "Restore complete. The active .env was preserved; its database and broker credentials must match the backup."
if [[ -f "$ROOT/config/deployment.env" ]]; then
    echo "The backed-up .env is available at config/deployment.env; compare credentials without overwriting this host's paths."
fi
