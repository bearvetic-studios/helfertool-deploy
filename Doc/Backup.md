[[_TOC_]]

# Backup und Wiederherstellung

## Konfiguration und Umfang

Die gemeinsamen Pfade in `.env` setzen:

```dotenv
HELFERTOOL_STORAGE_PATH=/srv/helfertool
HELFERTOOL_BACKUP_PATH=/mnt/backup/helfertool
```

Ohne diese Einstellungen gelten `./storage` und `./backups` relativ zum Stack-Verzeichnis. Die Skripte verwenden die von Docker Compose aufgeloeste Konfiguration; shellseitiges `source .env` ist nicht erforderlich. Daten- und Backup-Pfade mit Leerzeichen werden unterstuetzt. Der Backuppfad darf nicht innerhalb des Datenpfads liegen.

Ein Backup enthaelt:

| Archiveintrag | Inhalt |
| --- | --- |
| `config/helfertool.yaml` | Generierte Anwendungs-, Mail- und Zugangskonfiguration aus `$HELFERTOOL_STORAGE_PATH/config` |
| `config/deployment.env` | Kopie der `.env` mit Passwoertern, Secret-Key und Deployment-Einstellungen |
| `storage/data` | Uploads und persistente Anwendungsdateien |
| `storage/postgres` | Vollstaendiger PostgreSQL-Datenbestand |
| `storage/rabbitmq` | Persistenter Broker-Zustand |

Logs und Runtime-Sockets sind nicht enthalten. Die Archivnamen bleiben unabhaengig vom konfigurierten absoluten Datenpfad gleich. Dadurch ist ein Restore an einem anderen Datenpfad moeglich. Aeltere Archive ohne `config/deployment.env` bleiben lesbar; deren urspruengliche Zugangsdaten muessen separat vorliegen.

Archive enthalten Geheimnisse. Sie werden mit Modus `0600` erstellt, das Standard-Backupverzeichnis mit `0700`. Der Zielordner muss Dateirechte und Hardlinks unterstuetzen; bei NFS die Berechtigungen und Mountoptionen vorher testen. Fuer ausser Haus gelagerte Kopien zusaetzlich Verschluesselung und geregelte Zugriffsrechte verwenden.

## Backup ausfuehren

Auf dem Linux-Docker-Host im Stack-Verzeichnis:

```sh
sudo bash scripts/backup.sh
```

Optional einen abweichenden Archivnamen angeben:

```sh
sudo bash scripts/backup.sh /mnt/backup/helfertool/vor-update.tar.gz
```

Das Skript stoppt Helfertool, PostgreSQL und RabbitMQ fuer eine konsistente Dateisicherung und startet danach die zuvor laufenden Dienste wieder. Es entsteht eine kurze Betriebsunterbrechung. Nicht gleichzeitig in Dockge deployen, Updates starten oder einen zweiten Sicherungslauf ausfuehren. Bereits vorhandene Archivnamen werden nicht ueberschrieben; fehlgeschlagene Archive werden nicht als fertiges Backup veroeffentlicht. Bei einem Sicherungsfehler werden die Dienste ebenfalls wieder gestartet, soweit Docker noch erreichbar ist.

Rueckgabecode und Erfolgsmeldung kontrollieren. Danach regelmaessig die Archivstruktur pruefen, ohne Inhalte mit Passwoertern auszugeben:

```sh
sudo tar -tzf /mnt/backup/helfertool/helfertool-ZEITSTEMPEL.tar.gz
```

Die Dateisicherung ist fuer PostgreSQL 17 und dieselbe Architektur vorgesehen. Fuer Hauptversions- oder Architekturwechsel einen PostgreSQL-Dump mit geplantem Import verwenden. Fuer die Wiederherstellung von RabbitMQ-Nachrichten auch den urspruenglichen Broker-Nodename/Hostname beibehalten; ein neuer Containerhostname kann zu einem neuen Broker-Datenverzeichnis fuehren. Anwendungsdaten und Veranstaltungen liegen in PostgreSQL, nicht ausschliesslich im Broker.

## Automatisieren

Beispiel fuer die root-Crontab, taeglich um 03:15 Uhr, mit einer Sperre gegen ueberlappende Laeufe:

```cron
15 3 * * * /usr/bin/flock -n /run/lock/helfertool-backup.lock /bin/bash -c 'cd /opt/stacks/helfertool && /bin/bash scripts/backup.sh' >> /var/log/helfertool-backup.log 2>&1
```

`flock` muss installiert sein. Sicherungsfehler und Speicherbelegung ueberwachen; der Cron-Eintrag allein versendet keine verlaessliche Alarmierung. Das Skript loescht keine alten Archive. Aufbewahrung, Kapazitaetsgrenzen und die zweite Kopie auf ein anderes System bewusst einrichten, beispielsweise im vorhandenen Backupwerkzeug.

Ein Backupverzeichnis auf derselben Platte ist kein Schutz vor Plattenausfall oder Verlust der VM. Eine zweite, moeglichst versionierte und extern gesicherte Kopie vorsehen. Proxmox-/PBS-Backups ergaenzen die Anwendungsbackups; passthrough-, Netzwerk- oder externe Mounts sind nicht automatisch Bestandteil einer VM-Sicherung. Restore mindestens einmal in einer separaten Test-VM pruefen.

## Wiederherstellen

Vorher die aktuelle Instanz separat sichern. Auf einem neuen Host Repository und Docker wie in der [Installationsanleitung](Deployment.md) vorbereiten, die gewuenschten Zielpfade in `.env` setzen und die urspruenglichen PostgreSQL-/RabbitMQ-Zugangsdaten sowie den urspruenglichen Secret-Key uebernehmen. Neue Passwoerter in `.env` aendern nicht die Benutzerpasswoerter in einer bereits bestehenden Datenbank.

Die gesicherte Umgebung kann vor dem Restore gezielt in eine geschuetzte temporaere Datei ausserhalb des Repositorys exportiert werden:

```sh
sudo install -m 600 /dev/null /root/helfertool-recovery.env
sudo sh -c 'tar -xOzf /mnt/backup/helfertool/helfertool-ZEITSTEMPEL.tar.gz config/deployment.env > /root/helfertool-recovery.env'
```

Zugangsdaten aus dieser Datei mit einem lokalen Editor in die aktive `.env` uebernehmen; nicht unbesehen die alten Pfade oder die Testdomain aktivieren. Die temporaere Datei nach Abschluss sicher verwahren oder entfernen. Bei aelteren Archiven fehlen diese Umgebungsdaten gegebenenfalls.

```sh
cd /opt/stacks/helfertool
sudo bash scripts/restore.sh /mnt/backup/helfertool/helfertool-ZEITSTEMPEL.tar.gz
```

Nur nach Pruefung mit `RESTORE` bestaetigen. Das Skript validiert die Archivpfade vor dem Stoppen, lehnt unter anderem Links und Pfadtraversierung ab und ersetzt dann Konfiguration, Anwendungsdaten, PostgreSQL und RabbitMQ an den konfigurierten Zielpfaden. Bei Fehlern vor erfolgreichem Abschluss versucht es, die vorherigen Dateien zurueckzulegen. Bei unvollstaendiger Rueckabwicklung genannte Recovery-Verzeichnisse nicht loeschen.

Die aktive `.env` bleibt unveraendert. Die gesicherte Kopie steht nach dem Restore zusaetzlich unter `config/deployment.env`; sie wird nicht automatisch ausgefuehrt oder als neue Deployment-Konfiguration eingesetzt. Die gesicherte Anwendungs-Konfiguration wird hingegen wiederhergestellt: Bei einem Domainwechsel nach dem Restore die erlaubten Hosts und eventuelle weitere Host-Einstellungen in `config/helfertool.yaml` sowie `.env` abgleichen.

Danach Dienststatus, HTTPS-Anmeldung, Veranstaltungen, Uploads und Hintergrundjobs kontrollieren. `init` auf wiederhergestellten Daten nicht erneut ausfuehren. Keine parallelen Container mit demselben PostgreSQL-Datenverzeichnis starten.

## Datenpfad wechseln

Das blosse Aendern von `HELFERTOOL_STORAGE_PATH` verschiebt keine vorhandenen Daten. Ein leerer Zielpfad wuerde als neue Installation erscheinen.

Sicherer Ablauf mit Wartungsfenster:

1. Mit dem bisherigen `.env`-Datenpfad ein Backup erstellen und dessen Lesbarkeit pruefen.
2. Den Stack mit `sudo docker compose stop` stoppen und bis zum Abschluss der Migration keine Schreibzugriffe zulassen.
3. Den neuen Datenpfad in `.env` setzen und den Zieldatentraeger auf korrekten Mount pruefen.
4. Das Backup mit `scripts/restore.sh` an den neuen Pfad wiederherstellen und die Instanz pruefen.
5. Den alten Datenpfad und das Backup erst nach erfolgreichem Restore-Test und einer weiteren Sicherung bereinigen.

Ein Kopieren laufender PostgreSQL-Dateien ist kein konsistentes Backup. `docker compose down` erhaelt die Bind-Mount-Daten. Trotzdem kein `down -v` und keine manuellen Loeschbefehle fuer Volumes oder Datenverzeichnisse verwenden, solange deren Inhalt nicht geprueft und gesichert ist.