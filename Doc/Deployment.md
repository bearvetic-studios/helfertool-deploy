[[_TOC_]]

# Installation auf Proxmox mit Docker und Dockge

## Architektur und Voraussetzungen

Empfehlung: eine eigene Debian-VM auf Proxmox mit Docker Engine und Compose v2. Docker nicht direkt auf dem Proxmox-Hypervisor installieren. Eine VM vermeidet die zusaetzlichen Berechtigungs- und Nesting-Anforderungen von Docker in LXC. Als Ausgangspunkt 2 bis 4 vCPU und 4 GB RAM vorsehen; den Bedarf anhand der Veranstaltungen und Hintergrundjobs messen.

Der Stack besteht aus PostgreSQL 17, RabbitMQ 4 und dem Wrapper-Image `ghcr.io/bearvetic-studios/helfertool` (auf Basis des offiziellen `helfertool/helfertool`-Images). Ein einmaliger `permissions`-Dienst setzt Rechte fuer den unprivilegierten Helfertool-Benutzer mit UID `10001`. Beim Start generiert der Container `/config/helfertool.yaml` automatisch aus den Umgebungsvariablen, fuehrt Datenbankmigrationen aus, initialisiert leere Instanzen einmalig (`helfertool init`) und legt den ersten Administrator an, falls noch kein Superuser existiert.

Der Runtime-Ordner sowie alle persistenten Daten (`helfertool-config`, `helfertool-data`, `helfertool-log`, `helfertool-postgres`, `helfertool-rabbitmq`, `helfertool-runtime`) liegen standardmaessig in benannten Docker-/Podman-Volumes. Damit funktioniert `docker compose up -d` bzw. `podman compose up -d` sowie Dockge direkt ohne vorherige Ordnererstellung auf dem Host. Optional koennen die Daten ueber [`compose.bind-storage.yaml`](../compose.bind-storage.yaml) und `HELFERTOOL_STORAGE_PATH` auf einen lokalen SSD-Pfad gebunden werden (nicht auf NFS/SMB).

Fuer den produktiven Zugriff ist ein HTTPS-Reverse-Proxy (z. B. `cloudflared` oder nginx) notwendig. Ein SMTP-Server wird fuer Anwendungs-E-Mails benoetigt und laesst sich direkt ueber `.env` konfigurieren.

## Deployment in Dockge (ohne Git-Clone auf dem Host)

In Dockge einen neuen Stack (z. B. `helfertool`) anlegen und den Inhalt von [`compose.yaml`](../compose.yaml) sowie [`.env.example`](../.env.example) direkt in Dockge uebernehmen. Es muessen keine Skripte oder Konfigurationsdateien vorab auf den Host kopiert werden.

Wichtige Einstellungen im Dockge-`.env`:

```dotenv
HELFERTOOL_IMAGE=ghcr.io/bearvetic-studios/helfertool:latest
HELFERTOOL_BIND_ADDRESS=192.168.1.100
HELFERTOOL_PORT=8080
HELFERTOOL_ALLOWED_HOSTS=helfer.bearvetic.ch
HELFERTOOL_BEHIND_PROXY=true
```

Alle `REPLACE_...`-Platzhalter ersetzen:

* **`HELFERTOOL_SECRET_KEY`:** Zufaelliger, dauerhaft unveraenderter Wert mit mindestens 50 Zeichen, z. B. ueber `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
* **`HELFERTOOL_ADMIN_USER` / `HELFERTOOL_ADMIN_EMAIL` / `HELFERTOOL_ADMIN_PASSWORD`:** Zugangsdaten fuer den ersten Administrator. Wird nur ausgefuehrt, solange noch kein Superuser in der Datenbank existiert.
* **`POSTGRES_PASSWORD` & `RABBITMQ_PASSWORD`:** Unterschiedliche, starke Passwoerter.
* **`HELFERTOOL_BIND_ADDRESS`:**
  * `127.0.0.1`, wenn der Reverse-Proxy direkt auf demselben Docker-Host laeuft.
  * Die private LAN-IP der Docker-VM (z. B. `192.168.1.100`), wenn `cloudflared` in einem separaten LXC-Container/Host laeuft. Nicht unnoetig `0.0.0.0` verwenden und Zugriff per Firewall begrenzen.
* **Optional SMTP (`SMTP_HOST` etc.):** Sobald `SMTP_HOST` gesetzt ist, wird der `mail.send`-Block automatisch in `/config/helfertool.yaml` erzeugt.
* **`HELFERTOOL_IMAGE`:** Fuer Produktion nach Moeglichkeit einen gepinnten Versionstag statt `latest` verwenden.

Anschliessend in Dockge auf **Deploy** klicken. Der erste Start dauert etwas laenger, da Migrationen und `helfertool init` automatisch laufen.

## HTTPS und Cloudflare Tunnel (`cloudflared`)

Empfehlung fuer die Produktion: Subdomain wie `https://helfer.bearvetic.ch/`.

* `HELFERTOOL_ALLOWED_HOSTS=helfer.bearvetic.ch` und `HELFERTOOL_BEHIND_PROXY=true` setzen. Dadurch wertet Helfertool den Header `X-Forwarded-Proto: https` korrekt aus und akzeptiert Session-/CSRF-Cookies ueber HTTPS.
* Im Cloudflare Tunnel (`cloudflared`) als Ziel `http://192.168.1.100:8080` (bzw. `http://helfertool:8000` im gemeinsamen Docker-Netzwerk) eintragen.
* Die Anmeldung nicht ueber unverschluesseltes HTTP testen: Bei `DEBUG=False` sind sichere Session- und CSRF-Cookies aktiv.

## Betrieb und Updates

In Dockge oder auf dem Host im Stack-Verzeichnis:

```sh
docker compose ps
docker compose logs --tail 100 helfertool
docker compose logs --tail 100 postgres rabbitmq
```

Der eingebaute Healthcheck prueft die Webantwort mit dem erlaubten Host sowie alle Supervisor-Dienste.

Vor jedem Update ein Backup erstellen, den gewaehlten Image-Tag in `.env` aktualisieren und in Dockge **Update** / **Deploy** ausfuehren. PostgreSQL-Hauptversion `17` nicht einfach durch eine andere Hauptversion ersetzen.

## Optional: Host-Skripte und Tests

Fuer automatisierte Dateisicherungen auf dem Linux-Host (z. B. per Cron auf ein gemountetes Backup-Ziel) stehen [`scripts/backup.sh`](../scripts/backup.sh) und [`scripts/restore.sh`](../scripts/restore.sh) zur Verfuegung. Details dazu siehe [Backup und Wiederherstellung](Backup.md).

Tests auf Linux mit Bash, Python 3 und GNU tar:

```sh
python3 -m unittest discover -s tests -v
```

## Weiterfuehrend

- [Backup, Restore und Datenpfadwechsel](Backup.md)
- [Lokaler HTTPS-Test auf Windows mit Podman](Local-HTTPS.md)
- [Offizielles Admin-Handbuch](https://docs.helfertool.org/admin/index.html)
