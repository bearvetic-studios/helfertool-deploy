import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (
    [shutil.which("docker-compose")] if shutil.which("docker-compose")
    else [shutil.which("docker"), "compose"] if shutil.which("docker")
    else None
)


@unittest.skipUnless(COMPOSE, "Docker Compose is required to validate the relay configuration")
class SmtpOAuthComposeTests(unittest.TestCase):
    def render(self, oauth=False, missing=None):
        values = {
            "HELFERTOOL_ALLOWED_HOSTS": "localhost",
            "HELFERTOOL_SECRET_KEY": "test-key-" * 8,
            "POSTGRES_DB": "helfertool",
            "POSTGRES_USER": "helfertool",
            "POSTGRES_PASSWORD": "database-test-password",
            "RABBITMQ_VHOST": "helfertool",
            "RABBITMQ_USER": "helfertool",
            "RABBITMQ_PASSWORD": "broker-test-password",
        }
        if oauth:
            values.update({
                "SMTP_HOST": "old-smtp.example.org",
                "SMTP_PORT": "465",
                "SMTP_USER": "old-login",
                "SMTP_PASSWORD": "old-password",
                "SMTP_TLS": "true",
                "SMTP_STARTTLS": "true",
                "SMTP_SENDER_ADDRESS": "helfer@example.org",
                "SMTP_SENDER_NAME": "Helfer Team",
                "OAUTH_TENANT_ID": "test-tenant",
                "OAUTH_CLIENT_ID": "test-client",
                "OAUTH_USERNAME": "login@example.org",
            })
        if missing:
            del values[missing]
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("SMTP_", "OAUTH_", "HELFERTOOL_", "POSTGRES_", "RABBITMQ_", "COMPOSE_"))
        }
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "test.env"
            env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
            command = [
                *COMPOSE, "--project-name", "smtp-oauth-test", "--env-file", str(env_file),
                "-f", str(ROOT / "compose.yaml"),
            ]
            if oauth:
                command.extend(["-f", str(ROOT / "compose.smtp-oauth.yaml")])
            return subprocess.run(
                [*command, "config", "--format", "json"],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
            )

    def test_base_stack_does_not_require_oauth_credentials(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertNotIn("smtp-relay", config["services"])
        self.assertEqual(config["services"]["helfertool"]["environment"]["SMTP_PORT"], "587")

    def test_relay_override_routes_mail_and_isolates_credentials_and_networks(self):
        result = self.render(oauth=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        app = config["services"]["helfertool"]
        relay = config["services"]["smtp-relay"]
        env = app["environment"]
        self.assertEqual(
            {key: env[key] for key in (
                "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_TLS", "SMTP_STARTTLS",
            )},
            {
                "SMTP_HOST": "smtp-relay", "SMTP_PORT": "8025", "SMTP_USER": "",
                "SMTP_PASSWORD": "", "SMTP_TLS": "false", "SMTP_STARTTLS": "false",
            },
        )
        self.assertEqual(env["SMTP_SENDER_ADDRESS"], "helfer@example.org")
        self.assertEqual(env["SMTP_SENDER_NAME"], "Helfer Team")
        self.assertNotIn("OAUTH_CLIENT_SECRET", env)
        self.assertNotIn("OAUTH_USERNAME", env)
        self.assertNotIn("OAUTH_CLIENT_SECRET", relay["environment"])
        self.assertEqual(relay["environment"]["OAUTH_USERNAME"], "login@example.org")
        self.assertEqual(relay["environment"]["SMTP_SENDER_ADDRESS"], "helfer@example.org")
        self.assertEqual(app["depends_on"]["smtp-relay"]["condition"], "service_healthy")
        self.assertFalse(relay.get("ports"))
        self.assertEqual(set(relay["networks"]), {"smtp-internal", "smtp-egress"})
        self.assertTrue(config["networks"]["smtp-internal"]["internal"])
        self.assertEqual(set(app["networks"]) & set(relay["networks"]), {"smtp-internal"})
        self.assertTrue(any(
            mount["type"] == "volume" and mount["target"] == "/data"
            for mount in relay["volumes"]
        ))

    def test_relay_override_rejects_missing_required_settings(self):
        for key in (
            "OAUTH_TENANT_ID", "OAUTH_CLIENT_ID", "OAUTH_USERNAME", "SMTP_SENDER_ADDRESS",
        ):
            with self.subTest(key=key):
                result = self.render(oauth=True, missing=key)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(key, result.stderr)


if __name__ == "__main__":
    unittest.main()
