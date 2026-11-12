import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "docker"))

import generate_config  # noqa: E402


class GenerateConfigTests(unittest.TestCase):
    def base_env(self):
        return {
            "HELFERTOOL_ALLOWED_HOSTS": "helfer.bearvetic.ch,localhost",
            "HELFERTOOL_SECRET_KEY": "secret-key-" * 6,
            "POSTGRES_DB": "helfertool",
            "POSTGRES_USER": "helfertool",
            "POSTGRES_PASSWORD": "database-test-password",
            "RABBITMQ_VHOST": "helfertool",
            "RABBITMQ_USER": "helfertool",
            "RABBITMQ_PASSWORD": "broker-test-password",
        }

    def test_generates_defaults_including_behind_proxy_and_timezone(self):
        lines = generate_config.build_config_lines(self.base_env())
        content = "\n".join(lines)
        self.assertIn('default: "de"', content)
        self.assertIn('timezone: "Europe/Zurich"', content)
        self.assertIn("behind_proxy: true", content)
        self.assertIn("debug: false", content)
        self.assertIn('"helfer.bearvetic.ch"', content)
        self.assertNotIn("mail:", content)

    def test_generates_smtp_section_when_smtp_host_is_set(self):
        env = self.base_env()
        env.update({
            "SMTP_HOST": "mail.bearvetic.ch",
            "SMTP_PORT": "587",
            "SMTP_USER": "noreply@bearvetic.ch",
            "SMTP_PASSWORD": "smtp-secret-password",
            "SMTP_TLS": "false",
            "SMTP_STARTTLS": "true",
        })
        content = "\n".join(generate_config.build_config_lines(env))
        self.assertIn("mail:", content)
        self.assertIn('host: "mail.bearvetic.ch"', content)
        self.assertIn("port: 587", content)
        self.assertIn('user: "noreply@bearvetic.ch"', content)
        self.assertIn("tls: false", content)
        self.assertIn("starttls: true", content)

    def test_rejects_placeholders_and_short_secret(self):
        env = self.base_env()
        env["POSTGRES_PASSWORD"] = "REPLACE_WITH_PASSWORD"
        with self.assertRaises(ValueError):
            generate_config.build_config_lines(env)

        env = self.base_env()
        env["HELFERTOOL_SECRET_KEY"] = "too-short"
        with self.assertRaises(ValueError):
            generate_config.build_config_lines(env)

    def test_write_config_sets_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / "helfertool.yaml"
            lines = generate_config.build_config_lines(self.base_env())
            generate_config.write_config(config_path, lines)
            self.assertTrue(config_path.is_file())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()

