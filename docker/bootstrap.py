#!/usr/bin/env python3
"""Idempotent first-time initialization and superuser creation for Helfertool."""

import os
import re
import subprocess
import sys
from pathlib import Path


INIT_MARKER = Path("/data/.helfertool_initialized")
PLACEHOLDER_RE = re.compile(r"replace|change.?me", re.IGNORECASE)


def main() -> None:
    """Run helfertool init once on empty databases and ensure an admin user exists."""
    sys.path.insert(0, "/helfertool/src")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "helfertool.settings_container")

    import django
    django.setup()

    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    has_users = user_model.objects.exists()

    if not INIT_MARKER.exists() and not has_users:
        print("Running initial helfertool init...")
        subprocess.run(["/usr/local/bin/helfertool", "init"], check=True)
        INIT_MARKER.write_text("initialized\n", encoding="utf-8")
    elif not INIT_MARKER.exists() and has_users:
        # Restored or pre-existing database: record marker without overwriting existing data.
        INIT_MARKER.write_text("initialized\n", encoding="utf-8")

    admin_user = os.environ.get("HELFERTOOL_ADMIN_USER", "").strip()
    admin_email = os.environ.get("HELFERTOOL_ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("HELFERTOOL_ADMIN_PASSWORD", "")

    if not admin_user and not admin_email and not admin_password:
        if not user_model.objects.filter(is_superuser=True).exists():
            print(
                "Warning: No superuser exists and HELFERTOOL_ADMIN_* variables are not set.",
                file=sys.stderr,
            )
        return

    if not admin_user or not admin_email or not admin_password:
        raise ValueError(
            "HELFERTOOL_ADMIN_USER, HELFERTOOL_ADMIN_EMAIL, and HELFERTOOL_ADMIN_PASSWORD "
            "must all be set to create the initial admin user."
        )

    if PLACEHOLDER_RE.search(admin_password):
        raise ValueError("HELFERTOOL_ADMIN_PASSWORD still contains a placeholder; set a real password.")

    if user_model.objects.filter(is_superuser=True).exists():
        print("Superuser already exists; skipping automatic creation.")
        return

    print(f"Creating initial superuser {admin_user!r}...")
    user_model.objects.create_superuser(
        username=admin_user,
        email=admin_email,
        password=admin_password,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Bootstrap error: {error}", file=sys.stderr)
        sys.exit(1)

