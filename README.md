# Helfertool mit Dockge und Docker Compose

Dieses Repository stellt Helfertool mit PostgreSQL und RabbitMQ als Dockge-kompatiblen Compose-Stack bereit. Die Daten liegen in lokalen Verzeichnissen unter `storage/`; die Weboberfläche wird standardmäßig nur an `127.0.0.1:8080` gebunden. Für den öffentlichen Zugriff einen Reverse Proxy vorschalten.

## Voraussetzungen

- Docker Engine mit Docker Compose v2
- Python 3 und Bash
- Dockge (optional, für die Stack-Verwaltung im Browser)

## Erstinstallation

1. Das Repository auf den Docker-Host klonen und in das Verzeichnis wechseln.
2. Umgebung anlegen und sichere Zugangsdaten setzen:

   ```sh
   cp .env.example .env
   chmod 600 .env
   ```

   Ersetze alle `REPLACE_...`-Platzhalter. Erzeuge für `HELFERTOOL_SECRET_KEY` einen zufälligen Wert mit mindestens 50 Zeichen, zum Beispiel mit `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Wähle unterschiedliche, starke Passwörter für PostgreSQL und RabbitMQ. Trage in `HELFERTOOL_ALLOWED_HOSTS` die Hostnamen ein, über die Helfertool tatsächlich erreichbar ist. Ändere bei Bedarf `HELFERTOOL_BIND_ADDRESS` und `HELFERTOOL_PORT`.

3. Stack starten:

   ```sh
   ./scripts/start.sh
   ```

   Das Skript erzeugt `config/helfertool.yaml` aus `.env`, legt die persistenten Datenverzeichnisse an, setzt die für den nicht privilegierten Helfertool-Container erforderlichen Rechte und startet die Dienste. Konfiguration und Zugangsdaten werden nicht eingecheckt.

## Dockge

Lege den geklonten Ordner als Stack in Dockge an. `.env` und `config/helfertool.yaml` müssen vor dem ersten Start erstellt sein; dafür einmal `./scripts/start.sh` ausführen. Dockge muss den Ordner `.env` als Compose-Umgebungsdatei verwenden und denselben Stack-Pfad benutzen, damit die relativen Bind-Mounts auf die richtigen Verzeichnisse zeigen. Der Compose-Stack führt den einmaligen Dienst `permissions` vor Helfertool aus; PostgreSQL und RabbitMQ müssen zuvor gesund sein.

Die `permissions`-Initialisierung benötigt root-Rechte, um die Datenverzeichnisse für die Image-UID `10001` beschreibbar zu machen. Der Helfertool-Container selbst läuft weiterhin unprivilegiert. PostgreSQL und RabbitMQ sind nicht auf Host-Ports veröffentlicht.

## Konfiguration und Betrieb

`scripts/generate-config.py` liest die nötigen Werte aus `.env` und schreibt YAML-Strings als JSON-kompatible YAML-Strings. Ungültige oder nicht ersetzte Zugangsdaten sowie ein zu kurzer Secret-Key brechen mit einer Fehlermeldung ab. Die Konfigurationsdatei wird atomar mit Modus `0600` erstellt; der Konfigurationsordner erhält Modus `0750`. Compose und das Startskript erwarten `.env` im Stack-Verzeichnis.

Nützliche Befehle:

```sh
docker compose --env-file .env -f compose.yaml ps
docker compose --env-file .env -f compose.yaml logs -f helfertool
docker compose --env-file .env -f compose.yaml down
```

`down` erhält die Daten. **`docker compose down -v` nicht verwenden**, wenn Daten behalten werden sollen.

## Backup und Wiederherstellung

Ein konsistentes Backup stoppt Helfertool und beide Datendienste kurzzeitig:

```sh
./scripts/backup.sh
# oder: ./scripts/backup.sh /sicherer/pfad/helfertool.tar.gz
```

Das Archiv enthält die generierte Helfertool-Konfiguration sowie Daten-, PostgreSQL- und RabbitMQ-Verzeichnisse. Es kann Geheimnisse enthalten und wird mit Modus `0600` gespeichert. Bewahre es sicher und außerhalb dieses Repositorys auf. `.env` ist absichtlich nicht enthalten: Sichere sie getrennt und vertraulich. Bei der Wiederherstellung müssen die Datenbank- und RabbitMQ-Zugangsdaten in `.env` zu den Zugangsdaten im Backup passen.

Wiederherstellung ersetzt die aktuelle Konfiguration und die gespeicherten Daten. Das Skript prüft zuerst die Archivpfade und verlangt eine ausdrückliche Bestätigung:

```sh
./scripts/restore.sh backups/helfertool-JJJJMMTTHHMMSSZ.tar.gz
```

## Gesundheitsprüfungen

Compose prüft PostgreSQL mit `pg_isready`, RabbitMQ mit `rabbitmq-diagnostics ping` und Helfertool mit dem Healthcheck des offiziellen Images. Helfertool wird erst gestartet, wenn beide Datendienste gesund sind.
