#!/usr/bin/env bash
set -Eeuo pipefail

cd /helfertool/src
host="$(/helfertool/venv/bin/python manage.py shell --verbosity 0 -c 'from django.conf import settings; print(settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "")')"
curl --fail --silent --output /dev/null -H "Host: $host" http://localhost:8000

status="$(supervisorctl -c /helfertool/run/supervisord.conf status)"
if [[ -z "$status" ]]; then
    exit 1
fi
while read -r service state details; do
    if [[ "$state" != "RUNNING" ]]; then
        printf 'Service %s is %s\n' "$service" "$state" >&2
        exit 1
    fi
done <<< "$status"