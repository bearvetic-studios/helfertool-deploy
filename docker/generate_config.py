#!/usr/bin/env python3
"""Generate /config/helfertool.yaml safely from container environment variables."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path


CONFIG_FILE = Path(os.environ.get("HELFERTOOL_CONFIG_FILE", "/config/helfertool.yaml"))
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
PLACEHOLDER_RE = re.compile(r"replace|change.?me", re.IGNORECASE)


def yaml_string(value: str) -> str:
    """Serialize a string safely as a JSON-compatible YAML scalar."""
    return json.dumps(value, ensure_ascii=True)


def parse_bool(value: str, default: bool) -> bool:
    """Parse common boolean environment variable values."""
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def build_config_lines(env: dict[str, str]) -> list[str]:
    """Validate environment variables and return YAML lines for helfertool.yaml."""
    missing = [key for key in REQUIRED if not env.get(key, "").strip()]
    if missing:
        raise ValueError("Missing required settings: " + ", ".join(missing))

    for key in REQUIRED:
        if PLACEHOLDER_RE.search(env[key]):
            raise ValueError(f"{key} still contains a placeholder; set a real value in .env.")

    if len(env["HELFERTOOL_SECRET_KEY"]) < 50:
        raise ValueError("HELFERTOOL_SECRET_KEY must contain at least 50 characters.")

    hosts = [host.strip() for host in env["HELFERTOOL_ALLOWED_HOSTS"].split(",")]
    if any(not host for host in hosts):
        raise ValueError("HELFERTOOL_ALLOWED_HOSTS must be a comma-separated list of hosts.")

    language = env.get("HELFERTOOL_LANGUAGE", "").strip() or "de"
    timezone = env.get("HELFERTOOL_TIMEZONE", "").strip() or "Europe/Zurich"
    behind_proxy = parse_bool(env.get("HELFERTOOL_BEHIND_PROXY", "true"), True)

    lines = [
        "language:",
        f"    default: {yaml_string(language)}",
        f"timezone: {yaml_string(timezone)}",
        "database:",
        '    backend: "postgresql"',
        f"    name: {yaml_string(env['POSTGRES_DB'])}",
        f"    user: {yaml_string(env['POSTGRES_USER'])}",
        f"    password: {yaml_string(env['POSTGRES_PASSWORD'])}",
        '    host: "postgres"',
        "    port: 5432",
        "rabbitmq:",
        f"    vhost: {yaml_string(env['RABBITMQ_VHOST'])}",
        f"    user: {yaml_string(env['RABBITMQ_USER'])}",
        f"    password: {yaml_string(env['RABBITMQ_PASSWORD'])}",
        '    host: "rabbitmq"',
        "    port: 5672",
        "security:",
        "    debug: false",
        f"    behind_proxy: {'true' if behind_proxy else 'false'}",
        f"    secret: {yaml_string(env['HELFERTOOL_SECRET_KEY'])}",
        "    allowed_hosts:",
    ]
    lines.extend(f"        - {yaml_string(host)}" for host in hosts)

    smtp_host = env.get("SMTP_HOST", "").strip()
    if smtp_host:
        if PLACEHOLDER_RE.search(smtp_host):
            raise ValueError("SMTP_HOST still contains a placeholder; set a real value or leave it empty.")
        smtp_port_raw = env.get("SMTP_PORT", "").strip() or "587"
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError as error:
            raise ValueError(f"SMTP_PORT must be an integer, got {smtp_port_raw!r}.") from error
        smtp_user = env.get("SMTP_USER", "").strip()
        smtp_password = env.get("SMTP_PASSWORD", "")
        smtp_tls = parse_bool(env.get("SMTP_TLS", "false"), False)
        smtp_starttls = parse_bool(env.get("SMTP_STARTTLS", "true"), True)
        lines.extend([
            "mail:",
            "    send:",
            f"        host: {yaml_string(smtp_host)}",
            f"        port: {smtp_port}",
            f"        user: {yaml_string(smtp_user) if smtp_user else 'null'}",
            f"        password: {yaml_string(smtp_password) if smtp_password else 'null'}",
            f"        tls: {'true' if smtp_tls else 'false'}",
            f"        starttls: {'true' if smtp_starttls else 'false'}",
        ])

    return lines


def write_config(config_path: Path, lines: list[str]) -> None:
    """Atomically write the configuration file with restrictive permissions."""
    config_dir = config_path.parent
    if not config_dir.exists():
        config_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".helfertool.", dir=config_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, config_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> None:
    """Generate helfertool.yaml from the current process environment."""
    lines = build_config_lines(dict(os.environ))
    write_config(CONFIG_FILE, lines)
    print(f"Generated {CONFIG_FILE} with mode 0600.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        sys.exit(1)

