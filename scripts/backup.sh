#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
    echo "Missing .env; copy .env.example to .env first." >&2
    exit 1
fi

COMPOSE=(docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" --env-file "$ROOT/.env")
BACKUP_DIR="$ROOT/backups"
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [backup-file.tar.gz]" >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    ARCHIVE="$1"
    [[ "$ARCHIVE" = /* ]] || ARCHIVE="$ROOT/$ARCHIVE"
else
    ARCHIVE="$BACKUP_DIR/helfertool-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
fi
mkdir -p -- "$(dirname -- "$ARCHIVE")"

RUNNING_SERVICES="$("${COMPOSE[@]}" ps --services --status running)"
restart_services() {
    if [[ -n "$RUNNING_SERVICES" ]]; then
        mapfile -t services <<<"$RUNNING_SERVICES"
        "${COMPOSE[@]}" start "${services[@]}" >/dev/null
    fi
}
trap restart_services EXIT

"${COMPOSE[@]}" stop helfertool postgres rabbitmq
tar --numeric-owner -czf "$ARCHIVE" -C "$ROOT" config/helfertool.yaml storage/data storage/postgres storage/rabbitmq
chmod 0600 "$ARCHIVE"
restart_services
trap - EXIT
echo "Backup written to $ARCHIVE"
