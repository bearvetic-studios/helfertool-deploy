import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.stack = self.base / "stack"
        shutil.copytree(ROOT / "scripts", self.stack / "scripts")
        (self.stack / ".env").write_text("TEST_ENV=preserve\n")
        (self.stack / "config").mkdir()
        (self.stack / "config" / "helfertool.yaml").write_text("original config\n")
        self.storage = self.base / "persistent data"
        self.backups = self.base / "offsite backups"
        for service in ("data", "postgres", "rabbitmq", "log"):
            (self.storage / service).mkdir(parents=True)
            (self.storage / service / "state").write_text(f"original {service}\n")
        self.config = self.base / "compose.json"
        self.write_config()
        self.calls = self.base / "calls.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "arguments = sys.argv[1:]\n"
            "with open(os.environ['TEST_CALLS'], 'a') as output:\n"
            "    output.write(json.dumps(arguments) + '\\n')\n"
            "if arguments[-3:] == ['config', '--format', 'json']:\n"
            "    print(Path(os.environ['TEST_CONFIG']).read_text())\n"
            "elif 'ps' in arguments:\n"
            "    print('helfertool\\npostgres\\nrabbitmq')\n"
            "elif os.environ.get('TEST_FAIL_COMMAND') in arguments:\n"
            "    sys.exit(1)\n"
        )
        docker.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "TEST_CALLS": str(self.calls),
            "TEST_CONFIG": str(self.config),
        }

    def write_config(self, backup=None):
        self.config.write_text(json.dumps({
            "services": {
                "helfertool": {"volumes": [{
                    "type": "bind", "target": "/data", "source": str(self.storage / "data")
                }]},
                "postgres": {"volumes": [{
                    "type": "bind", "target": "/var/lib/postgresql/data", "source": str(self.storage / "postgres")
                }]},
                "rabbitmq": {"volumes": [{
                    "type": "bind", "target": "/var/lib/rabbitmq", "source": str(self.storage / "rabbitmq")
                }]},
            },
            "x-backup-path": str(backup or self.backups),
        }))

    def run_script(self, name, *arguments, confirmation="", success=True):
        result = subprocess.run(
            ["bash", str(self.stack / "scripts" / name), *map(str, arguments)],
            cwd=self.stack,
            env=self.environment,
            input=confirmation,
            text=True,
            capture_output=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def commands(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def backup(self):
        self.run_script("backup.sh")
        return next(self.backups.glob("*.tar.gz"))

    def test_backup_uses_external_paths_and_portable_layout(self):
        archive = self.backup()
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        with tarfile.open(archive) as backup:
            self.assertEqual(set(backup.getnames()), {
                "config/helfertool.yaml", "config/deployment.env", "storage/data", "storage/data/state",
                "storage/postgres", "storage/postgres/state",
                "storage/rabbitmq", "storage/rabbitmq/state",
            })
        self.assertTrue(any("stop" in call for call in self.commands()))
        self.assertTrue(any("start" in call for call in self.commands()))
        self.assertFalse(list(self.backups.glob(".helfertool-backup.*")))

    def test_start_creates_external_storage_and_generates_config(self):
        values = {
            "HELFERTOOL_ALLOWED_HOSTS": "localhost,127.0.0.1",
            "HELFERTOOL_SECRET_KEY": "test-secret-" * 6,
            "POSTGRES_DB": "helfertool",
            "POSTGRES_USER": "helfertool",
            "POSTGRES_PASSWORD": "database-test-password",
            "RABBITMQ_VHOST": "helfertool",
            "RABBITMQ_USER": "helfertool",
            "RABBITMQ_PASSWORD": "broker-test-password",
        }
        (self.stack / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        shutil.rmtree(self.storage)
        self.run_script("start.sh")
        for service in ("data", "postgres", "rabbitmq", "log"):
            self.assertTrue((self.storage / service).is_dir())
        self.assertIn('backend: "postgresql"', (self.stack / "config" / "helfertool.yaml").read_text())
        self.assertTrue(any("permissions" in call and "run" in call for call in self.commands()))
        self.assertTrue(any("up" in call for call in self.commands()))

    def test_backup_failure_restarts_services_and_removes_partial_archive(self):
        shutil.rmtree(self.storage / "postgres")
        self.run_script("backup.sh", success=False)
        self.assertTrue(any("start" in call for call in self.commands()))
        self.assertFalse(list(self.backups.iterdir()))

    def test_backup_does_not_overwrite_existing_archive(self):
        archive = self.backup()
        previous = archive.read_bytes()
        self.run_script("backup.sh", archive, success=False)
        self.assertEqual(archive.read_bytes(), previous)

    def test_backup_rejects_archive_inside_storage(self):
        self.run_script("backup.sh", self.storage / "data" / "backup.tar.gz", success=False)
        self.assertFalse(any("stop" in call for call in self.commands()))

    def test_restore_can_use_a_different_storage_path_and_preserves_env(self):
        archive = self.backup()
        self.storage = self.base / "new server data"
        self.write_config()
        self.run_script("restore.sh", archive, confirmation="RESTORE\n")
        for service in ("data", "postgres", "rabbitmq"):
            self.assertEqual((self.storage / service / "state").read_text(), f"original {service}\n")
        self.assertEqual((self.stack / ".env").read_text(), "TEST_ENV=preserve\n")
        self.assertEqual((self.stack / "config" / "deployment.env").read_text(), "TEST_ENV=preserve\n")
        self.assertEqual(stat.S_IMODE((self.stack / "config" / "deployment.env").stat().st_mode), 0o600)
        self.assertFalse(list(self.storage.glob(".restore.*")))

    def test_restore_failure_rolls_back_existing_data_and_config(self):
        archive = self.backup()
        for service in ("data", "postgres", "rabbitmq"):
            (self.storage / service / "state").write_text(f"current {service}\n")
        (self.stack / "config" / "helfertool.yaml").write_text("current config\n")
        self.environment["TEST_FAIL_COMMAND"] = "run"
        self.run_script("restore.sh", archive, confirmation="RESTORE\n", success=False)
        for service in ("data", "postgres", "rabbitmq"):
            self.assertEqual((self.storage / service / "state").read_text(), f"current {service}\n")
        self.assertEqual((self.stack / "config" / "helfertool.yaml").read_text(), "current config\n")
        self.assertEqual((self.storage / "log" / "state").read_text(), "original log\n")

    def test_restore_accepts_legacy_archive_without_environment_copy(self):
        archive = self.backup()
        legacy = self.base / "legacy.tar.gz"
        with tarfile.open(archive) as source, tarfile.open(legacy, "w:gz") as destination:
            for member in source.getmembers():
                if member.name != "config/deployment.env":
                    destination.addfile(member, source.extractfile(member) if member.isfile() else None)
        self.run_script("restore.sh", legacy, confirmation="RESTORE\n")
        self.assertFalse((self.stack / "config" / "deployment.env").exists())
        self.assertEqual((self.stack / ".env").read_text(), "TEST_ENV=preserve\n")

    def test_restore_rejects_archive_traversal_before_stopping_services(self):
        archive = self.base / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as backup:
            member = tarfile.TarInfo("../outside")
            member.size = 4
            backup.addfile(member, io.BytesIO(b"test"))
        self.run_script("restore.sh", archive, confirmation="RESTORE\n", success=False)
        self.assertFalse(any("stop" in call for call in self.commands()))
        self.assertFalse((self.base / "outside").exists())

    def test_restore_requires_explicit_confirmation(self):
        archive = self.backup()
        self.calls.write_text("")
        self.run_script("restore.sh", archive, confirmation="no\n", success=False)
        self.assertFalse(any("stop" in call for call in self.commands()))

    def test_relative_backup_path_is_resolved_from_stack_directory(self):
        self.write_config(backup="./relative backups")
        self.run_script("backup.sh")
        self.assertTrue(list((self.stack / "relative backups").glob("*.tar.gz")))

    def test_overlapping_storage_and_backup_paths_are_rejected(self):
        self.write_config(backup=self.storage / "backups")
        self.run_script("backup.sh", success=False)
        self.assertFalse(any("stop" in call for call in self.commands()))


if __name__ == "__main__":
    unittest.main()