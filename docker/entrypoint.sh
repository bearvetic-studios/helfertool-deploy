#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${1:-run}" == "run" ]]; then
    rm -f /helfertool/run/*.pid /helfertool/run/*.sock
    /helfertool/venv/bin/python /usr/local/lib/helfertool-deploy/generate_config.py
    /usr/local/bin/helfertool manage migrate --noinput
    /helfertool/venv/bin/python /usr/local/lib/helfertool-deploy/bootstrap.py
fi

exec /usr/local/bin/helfertool "$@"

