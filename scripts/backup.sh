#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/deployment.sh"
umask 077
mkdir -p -- "$BACKUP_DIR"
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
if [[ -e "$ARCHIVE" ]]; then
    echo "Backup already exists; choose a different archive name: $ARCHIVE" >&2
    exit 1
fi
ARCHIVE_DIRECTORY="$(cd -- "$(dirname -- "$ARCHIVE")" && pwd)"
if [[ "$ARCHIVE_DIRECTORY" == "$STORAGE" || "$ARCHIVE_DIRECTORY" == "$STORAGE/"* ]]; then
    echo "Backup archives must be outside HELFERTOOL_STORAGE_PATH." >&2
    exit 1
fi
TEMP_ARCHIVE="$(mktemp "$ARCHIVE_DIRECTORY/.helfertool-backup.XXXXXX")"

RUNNING_SERVICES="$("${COMPOSE[@]}" ps --services --status running)"
restart_services() {
    if [[ -n "$RUNNING_SERVICES" ]]; then
        mapfile -t services <<<"$RUNNING_SERVICES"
        "${COMPOSE[@]}" start "${services[@]}" >/dev/null
    fi
}
cleanup() {
    rm -f -- "$TEMP_ARCHIVE"
    restart_services
}
trap cleanup EXIT

"${COMPOSE[@]}" stop helfertool postgres rabbitmq
tar --numeric-owner --transform='s,^\(data\|postgres\|rabbitmq\)\(/\|$\),storage/\1\2,' \
    --transform='s,^\.env$,config/deployment.env,' \
    -czf "$TEMP_ARCHIVE" -C "$ROOT" config/helfertool.yaml .env -C "$STORAGE" data postgres rabbitmq
chmod 0600 "$TEMP_ARCHIVE"
ln -- "$TEMP_ARCHIVE" "$ARCHIVE"
rm -f -- "$TEMP_ARCHIVE"
restart_services
trap - EXIT
echo "Backup written to $ARCHIVE"
