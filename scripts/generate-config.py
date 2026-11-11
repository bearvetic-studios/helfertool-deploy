#!/usr/bin/env python3
"""Generate the Helfertool YAML config safely from the deployment .env file."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CONFIG_DIR = ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "helfertool.yaml"
REQUIRED = (
    "HELFERTOOL_ALLOWED_HOSTS",
    "HELFERTOOL_SECRET_KEY",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "RABBITMQ_VHOST",
    "RABBITMQ_USER",
    "RABBITMQ_PASSWORD",
)


def read_env(path):
    values = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path.name}:{line_number}: expected KEY=value")
        value = value.strip()
        if value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ValueError(f"{path.name}:{line_number}: unmatched single quote")
            value = value[1:-1]
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name}:{line_number}: invalid double-quoted value") from error
            if not isinstance(value, str):
                raise ValueError(f"{path.name}:{line_number}: expected a string value")
        values[key] = value
    return values


def yaml_string(value):
    return json.dumps(value, ensure_ascii=True)


def main():
    if not ENV_FILE.is_file():
        raise ValueError("Missing .env; copy .env.example to .env and set real values.")

    values = read_env(ENV_FILE)
    values.update({key: value for key, value in os.environ.items() if key in REQUIRED})
    missing = [key for key in REQUIRED if not values.get(key, "").strip()]
    if missing:
        raise ValueError("Missing required settings: " + ", ".join(missing))

    for key in REQUIRED:
        if re.search(r"replace|change.?me", values[key], re.IGNORECASE):
            raise ValueError(f"{key} still contains a placeholder; set a real value in .env.")

    if len(values["HELFERTOOL_SECRET_KEY"]) < 50:
        raise ValueError("HELFERTOOL_SECRET_KEY must contain at least 50 characters.")

    hosts = [host.strip() for host in values["HELFERTOOL_ALLOWED_HOSTS"].split(",")]
    if any(not host for host in hosts):
        raise ValueError("HELFERTOOL_ALLOWED_HOSTS must be a comma-separated list of hosts.")

    lines = [
        "language:",
        '    default: "de"',
        "database:",
        '    backend: "postgresql"',
        f"    name: {yaml_string(values['POSTGRES_DB'])}",
        f"    user: {yaml_string(values['POSTGRES_USER'])}",
        f"    password: {yaml_string(values['POSTGRES_PASSWORD'])}",
        '    host: "postgres"',
        "    port: 5432",
        "rabbitmq:",
        f"    vhost: {yaml_string(values['RABBITMQ_VHOST'])}",
        f"    user: {yaml_string(values['RABBITMQ_USER'])}",
        f"    password: {yaml_string(values['RABBITMQ_PASSWORD'])}",
        '    host: "rabbitmq"',
        "    port: 5672",
        "security:",
        "    debug: false",
        f"    secret: {yaml_string(values['HELFERTOOL_SECRET_KEY'])}",
        "    allowed_hosts:",
    ]
    lines.extend(f"        - {yaml_string(host)}" for host in hosts)

    CONFIG_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o750)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".helfertool.", dir=CONFIG_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as config:
            config.write("\n".join(lines) + "\n")
            config.flush()
            os.fsync(config.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, CONFIG_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"Generated {CONFIG_FILE.relative_to(ROOT)} with mode 0600.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        sys.exit(1)
