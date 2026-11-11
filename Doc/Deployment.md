[[_TOC_]]

# Installation auf Proxmox mit Docker und Dockge

## Architektur und Voraussetzungen

Empfehlung: eine eigene Debian-VM auf Proxmox mit Docker Engine und Compose v2. Docker nicht direkt auf dem Proxmox-Hypervisor installieren. Eine VM vermeidet die zusaetzlichen Berechtigungs- und Nesting-Anforderungen von Docker in LXC. Als Ausgangspunkt 2 bis 4 vCPU und 4 GB RAM vorsehen; den Bedarf anhand der Veranstaltungen und Hintergrundjobs messen.

Auf dem Docker-Host werden Git, Python 3, Bash und GNU tar benoetigt. Die Betriebsskripte sind fuer Linux mit Docker Compose v2 gedacht. Backups und Wiederherstellungen mit root-Rechten ausfuehren, damit auch PostgreSQL-Dateien und numerische Eigentuemerdaten gelesen und wiederhergestellt werden koennen.

Der Stack besteht aus PostgreSQL 17, RabbitMQ 4 und dem offiziellen Helfertool-Image. Ein einmaliger root-Dienst setzt Rechte fuer den unprivilegierten Helfertool-Benutzer mit UID 10001. Der Runtime-Ordner liegt in einem benannten Linux-Volume: Dort liegen unter anderem Unix-Sockets, die nicht auf einem Windows-Dateisystem abgelegt werden sollen. Die dauerhaften Geschaeftsdaten liegen dagegen unter dem konfigurierten Datenpfad.

Fuer den produktiven Zugriff ist ein HTTPS-Reverse-Proxy notwendig. Ein SMTP-Server wird fuer Anwendungs-E-Mails benoetigt. Das Entwicklungssetup aus dem offiziellen Entwickler-Handbuch ist fuer diesen Betrieb nicht erforderlich.

## Repository und Pfade

Dockge und Docker muessen denselben Stack-Pfad sehen. Beispiel: `/opt/stacks` auf dem Docker-Host nach `/opt/stacks` im Dockge-Container einbinden und `DOCKGE_STACKS_DIR=/opt/stacks` setzen. Zusaetzlich benoetigt Dockge den Docker-Socket. Docker-Socket-Zugriff entspricht weitreichendem Host-Zugriff; Dockge nur im vertrauenswuerdigen Verwaltungsnetz erreichbar machen.

Repository-Adresse im folgenden Beispiel ersetzen:

```sh
sudo mkdir -p /opt/stacks
sudo git clone DEINE_REPOSITORY_URL /opt/stacks/helfertool
cd /opt/stacks/helfertool
sudo cp .env.example .env
sudo chmod 600 .env
sudo nano .env
```

Wichtige Einstellungen fuer ein Produktionssystem:

```dotenv
HELFERTOOL_STORAGE_PATH=/srv/helfertool
HELFERTOOL_BACKUP_PATH=/mnt/backup/helfertool
HELFERTOOL_BIND_ADDRESS=127.0.0.1
HELFERTOOL_PORT=8080
HELFERTOOL_ALLOWED_HOSTS=helfer.hgis.ch
```

Alle `REPLACE_...`-Werte ersetzen. Unterschiedliche, starke Passwoerter fuer PostgreSQL und RabbitMQ waehlen. Fuer `HELFERTOOL_SECRET_KEY` einen zufaelligen, dauerhaft unveraenderten Wert mit mindestens 50 Zeichen verwenden, beispielsweise aus `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.

Fuer `HELFERTOOL_IMAGE` einen getesteten veroeffentlichten Versionstag oder Digest aus den offiziellen [Versionshinweisen](https://docs.helfertool.org/admin/versions.html) waehlen. `latest` in der Beispieldatei ist fuer einen schnellen Test gedacht, nicht fuer unbeaufsichtigte Produktionsupdates.

`HELFERTOOL_STORAGE_PATH` enthaelt `data`, `log`, `postgres` und `rabbitmq`. Relative Pfade beginnen im Stack-Verzeichnis; absolute Linux-Pfade sind auf dem Server uebersichtlicher. Den Datenpfad auf einem Linux-Dateisystem mit Unix-Dateirechten anlegen, nicht auf SMB oder einem Windows-Bind-Mount. Fuer Datenbanken lokalen bzw. passend eingebundenen VM-Speicher verwenden. Der Backuppfad muss ausserhalb des Datenpfads liegen und sollte auf einem anderen Datentraeger oder gesicherten Backupziel liegen.

Externe Datentraeger und Backupmounts vor dem Start auf ihre tatsaechliche Einbindung pruefen, beispielsweise mit `findmnt -T /mnt/backup/helfertool`. Fehlt ein Mount, wuerde ein vorhandenes normales Verzeichnis sonst auf der Systemplatte beschrieben. Ein Pfadeintrag allein richtet weder einen Datentraeger noch eine Sicherung ein.

## Erststart und Dockge

```sh
cd /opt/stacks/helfertool
sudo bash scripts/start.sh
sudo docker compose ps
```

Das Startskript erstellt `config/helfertool.yaml` aus `.env`, legt die konfigurierten Datenverzeichnisse an und startet die Dienste. Docker Compose erhaelt ueber die gemeinsame Pfadauflosung dieselben Pfade wie Backup und Restore. Die Anwendung fuehrt beim Start Datenbankmigrationen aus; der erste Start kann laenger dauern.

In Dockge anschliessend die Stack-Liste neu einlesen und den vorhandenen Stack `helfertool` verwalten. Die Basiskonfiguration `compose.yaml` und die `.env` im Stack-Verzeichnis verwenden. Nicht nur den YAML-Inhalt in einen anderen Stack-Pfad kopieren: Die Skripte und `config/helfertool.yaml` gehoeren ebenfalls dazu. Die Dateien fuer lokalen HTTPS-Betrieb nicht fuer diesen Produktionsstack zuschalten.

`config/helfertool.yaml` enthaelt Geheimnisse und muss vor dem ersten Start ueber Dockge existieren. Den einmaligen Erststart deshalb auf dem Docker-Host ausfuehren. Ein erneuter Aufruf von `scripts/start.sh` erzeugt diese Datei neu: Manuelle Erweiterungen wie die Mailkonfiguration vorher sichern und anschliessend wieder einpflegen.

## HTTPS und Domain

Empfehlung fuer die Produktion: `https://helfer.hgis.ch/`. DNS auf den Reverse Proxy zeigen lassen, ein oeffentlich vertrauenswuerdiges Zertifikat verwenden und genau diese Domain in `HELFERTOOL_ALLOWED_HOSTS` eintragen. Der Unterpfad `https://hgis.ch/helfer` erfordert eine gesonderte Pruefung von URL-, Static- und Cookie-Pfaden und ist nicht Bestandteil dieser Konfiguration.

Ein nginx auf demselben Docker-Host kann gemaess [offizieller Reverse-Proxy-Anleitung](https://docs.helfertool.org/admin/installation.html#reverse-proxy) auf `127.0.0.1:8080` weiterleiten. Im HTTPS-vHost benoetigt die Proxy-Location mindestens:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_redirect off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50M;
}
```

TLS-Zertifikat, HTTP-zu-HTTPS-Weiterleitung und die uebrige vHost-Konfiguration entsprechend der offiziellen Anleitung einrichten. Die Anmeldung nicht ueber den direkten HTTP-Port testen: Helfertool verwendet bei `DEBUG=False` sichere Session- und CSRF-Cookies. `DEBUG` nicht als Umgehung einschalten und CSRF nicht deaktivieren.

Laeuft der Proxy in einem anderen Container, zeigt `127.0.0.1` dort auf den Proxy selbst. Entweder ein gemeinsames Docker-Netzwerk fuer den Proxy und den Dienst `helfertool:8000` einrichten oder den Hostport gezielt auf einer fuer den Proxy erreichbaren privaten Adresse veroeffentlichen. Bei einem Proxy auf einer anderen VM die private VM-IP als Bind-Adresse verwenden und den Zugriff per Firewall auf den Proxy begrenzen. Nicht unnoetig `0.0.0.0` verwenden. PostgreSQL und RabbitMQ bleiben ohne veroeffentlichte Hostports.

## Initialisierung und Administrator

Nach einem neuen, leeren Deployment die Anwendungsgrunddaten genau einmal laden:

```sh
sudo docker compose exec helfertool /usr/local/bin/helfertool init
```

Nach einem Restore oder auf einer bereits initialisierten Instanz `init` nicht erneut ausfuehren, da die Standardkonfiguration vorhandene Einstellungen ueberschreiben kann.

Den ersten Administrator interaktiv anlegen:

```sh
sudo docker compose exec helfertool /usr/local/bin/helfertool manage createsuperuser
```

Benutzername, E-Mail und Passwort direkt im Terminal eingeben. Das verwendete Image nennt `createadmin` in der Hilfe, implementiert diesen Unterbefehl aber nicht; `manage createsuperuser` wurde mit dem laufenden Image geprueft. Weitere Administratoren spaeter in der Weboberflaeche verwalten. Anmeldeseite ueber die HTTPS-Domain neu oeffnen.

## E-Mail und weitere Konfiguration

Vor produktiver Nutzung den Mailserver gemaess [offizieller Konfiguration](https://docs.helfertool.org/admin/configuration.html#mail-server) im erzeugten `config/helfertool.yaml` ergaenzen. Der Generator dieses Repositorys erzeugt die Grundkonfiguration fuer Datenbank, Broker und Sicherheit; SMTP ist nicht in `.env` vorbelegt. Nach Aenderungen Helfertool neu starten und den Mailversand mit einem kontrollierten Empfaenger pruefen.

```sh
sudo docker compose restart helfertool
```

Die Config-Datei und die Sicherungsarchive vertraulich behandeln. `.env`, `config`, Datenordner und Archive nicht committen. Bei externen Pfaden ausserhalb des Repositories greift dessen `.gitignore` nicht; diese Pfade ebenfalls nicht in andere Repositories aufnehmen.

## Betrieb und Updates

```sh
sudo docker compose ps
sudo docker compose logs --tail 100 helfertool
sudo docker compose logs --tail 100 postgres rabbitmq
```

Der lokale Healthcheck prueft die Webantwort mit einem erlaubten Host und alle Supervisor-Dienste. Er unterdrueckt die zusaetzliche Django-Shell-Banner-Ausgabe, die beim urspruenglichen Image den Host-Header ungueltig machte. Gesundheitsstatus allein ersetzt keine Pruefung von Anmeldung, E-Mail und Hintergrundjobs.

Vor jedem Update [Release- und Migrationshinweise](https://docs.helfertool.org/admin/updates.html) lesen und ein [Backup](Backup.md) erstellen. Den gewaehlten Helfertool-Tag bewusst in `.env` aktualisieren, dann:

```sh
sudo bash scripts/backup.sh
sudo docker compose pull
sudo docker compose up -d --wait --wait-timeout 180
```

PostgreSQL-Hauptversion 17 nicht einfach durch eine andere Hauptversion ersetzen; ein Wechsel braucht ein geplantes Datenbank-Upgrade. Ein Rollback nach einer inkompatiblen Datenmigration benoetigt das passende Backup und die dazugehoerigen alten Image-Versionen, nicht nur einen alten Anwendungstag.

## Deployment-Skripte pruefen

Unter Linux mit Bash, Python 3 und GNU tar:

```sh
python3 tests/test_deployment.py -v
```

Die Tests verwenden temporaere Daten und simulierte Docker-Compose-Aufrufe; sie greifen nicht auf einen laufenden Stack zu. Geprueft werden unter anderem externe Pfade mit Leerzeichen, Erststart, Archivstruktur, Dateirechte, Fehlerbehandlung, Restore-Rollback und aeltere Archive. Ein echter Restore-Test in einer separaten VM ist vor dem produktiven Einsatz trotzdem erforderlich.

## Weiterfuehrend

- [Backup, Restore und Datenpfadwechsel](Backup.md)
- [Lokaler HTTPS-Test auf Windows mit Podman](Local-HTTPS.md)
- [Offizielles Admin-Handbuch](https://docs.helfertool.org/admin/index.html)
- [Offizielle helfertoolctl-Befehle](https://docs.helfertool.org/admin/helfertoolctl.html): Die Debian-Wrapper-Befehle nicht parallel zur Compose-Verwaltung einsetzen.
- [Offizielles Entwickler-Handbuch](https://docs.helfertool.org/development/index.html): Fuer Aenderungen am Helfertool selbst, nicht fuer die Installation dieses Stacks.