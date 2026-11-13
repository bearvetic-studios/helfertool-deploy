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
* **`SMTP_SENDER_ADDRESS` / `SMTP_SENDER_NAME`:** Optionale Von-Adresse und Anzeigename unter `mail.sender_address` und `mail.sender_name`, unabhaengig vom SMTP-Anmeldekonto. Leere Werte lassen die Helfertool-Defaults unveraendert (Adresse: `helfertool@localhost`, Name: Absenderadresse).
* **`HELFERTOOL_IMAGE`:** Fuer Produktion nach Moeglichkeit einen gepinnten Versionstag statt `latest` verwenden.

Anschliessend in Dockge auf **Deploy** klicken. Der erste Start dauert etwas laenger, da Migrationen und `helfertool init` automatisch laufen.

## Optionales SMTP-zu-Graph-Relay mit Benutzeranmeldung

Der Zusatz [`compose.smtp-oauth.yaml`](../compose.smtp-oauth.yaml) aktiviert das eigene, kleine [Graph-Relay](../relay/graph_relay.py). Der Ablauf ist:

```text
Helfertool -- internes SMTP:8025 --> Relay -- HTTPS --> Graph /me/sendMail
                                     |
                                     +-- delegierte OAuth-Tokens von Entra ID
```

Diese Variante verwendet **keine Client Credentials**, kein Benutzerpasswort und kein SMTP AUTH bei Microsoft. Security Defaults muessen fuer den Versand daher nicht deaktiviert werden. Ohne den Zusatz bleibt der direkte SMTP-Versand unveraendert.

### Voraussetzungen in Microsoft 365

1. Eine **Single-Tenant-App-Registrierung** in Entra erstellen; Tenant-ID und Client-ID als GUID notieren.
2. Unter **Authentication > Advanced settings** die Option **Allow public client flows** aktivieren. Der Device-Code-Flow verwendet keine Redirect-URI und kein Client Secret.
3. Unter **Microsoft Graph > Delegated permissions** die Berechtigung **`Mail.Send.Shared`** hinzufuegen. Je nach Tenant ist Administratorzustimmung erforderlich. MSAL fordert die OpenID-/Offline-Zugriffsscopes fuer Anmeldung und automatische Token-Erneuerung mit an.
4. Mit einem Benutzer anmelden, der ein Exchange-Online-Postfach besitzt. `OAUTH_USERNAME` muss dessen tatsaechlichem Anmelde-UPN entsprechen.
5. Diesem **Benutzer** auf der Verteilerliste **Send As / Senden als** erteilen. Gruppenmitgliedschaft allein reicht nicht. Die Liste `helfer@hgis.ch` kann bestehen bleiben; sie muss nicht in ein Postfach umgewandelt werden.

In Exchange Online PowerShell als Administrator:

```powershell
Connect-ExchangeOnline
Add-RecipientPermission -Identity "helfer@hgis.ch" `
  -Trustee "dominic.ammann@hgis.ch" -AccessRights SendAs
```

Keine `SMTP.SendAsApp`-Berechtigung, Exchange-Service-Principal-Registrierung oder SMTP-AUTH-Freigabe erforderlich. Der Versand erfolgt ueber das angemeldete Benutzerpostfach (`/me/sendMail`), nicht ueber `/users/helfer@hgis.ch/sendMail`. Graph bekommt die Verteilerliste als MIME-From-Adresse; Exchange prueft das Send-As-Recht. Gesendete Nachrichten werden im Benutzerpostfach abgelegt.

Tenant-Richtlinien und Conditional Access gelten weiterhin. Wenn Device-Code-Anmeldung verboten ist, muss der Administrator einen erlaubten Anmeldeweg bestimmen; das Relay faellt nicht auf Benutzerpasswort oder Basic Auth zurueck.

Referenzen: [Graph: Versand als Benutzer, Gruppe oder Verteilerliste](https://learn.microsoft.com/en-us/graph/outlook-send-mail-from-other-user) und [Graph sendMail mit MIME](https://learn.microsoft.com/en-us/graph/api/user-sendmail).

### Gemeinsame Umgebungsdatei

In derselben Stack-`.env` die Werte aus [`.env.example`](../.env.example) ergaenzen:

```dotenv
SMTP_RELAY_IMAGE=ghcr.io/bearvetic-studios/helfertool-smtp-graph:latest
SMTP_SENDER_ADDRESS=helfer@hgis.ch
SMTP_SENDER_NAME="HGIS Helfertool"
OAUTH_TENANT_ID=<Tenant-ID-als-GUID>
OAUTH_CLIENT_ID=<Client-ID-als-GUID>
OAUTH_USERNAME=dominic.ammann@hgis.ch
```

Das Override setzt `SMTP_HOST=smtp-relay`, Port `8025`, leere SMTP-Zugangsdaten und deaktiviert TLS/STARTTLS nur fuer die lokale Verbindung. Vorhandene direkte SMTP-Einstellungen werden uebersteuert. OAuth-Daten werden nur dem Relay gegeben und nicht in die Helfertool-YAML geschrieben.

Beim Wechsel von der frueheren SMTP/XOAUTH2-Variante `OAUTH_CLIENT_SECRET`, `SMTP_RELAY_MAILBOX` und `SMTP_RELAY_HOSTNAME` entfernen sowie das alte `SMTP_RELAY_IMAGE` ersetzen. Falls diese Variante schon produktiv war, vor dem Ersetzen die alte Postfix-Warteschlange vollstaendig zustellen; sie wird nicht migriert. Keine Volumes pauschal loeschen.

### Deployment und erste Anmeldung

Die [Build-Pipeline](../.github/workflows/build.yml) veroeffentlicht nach Push auf `main` beide Images: Helfertool-Wrapper und Graph-Relay. Alternativ das Relay mit [`Dockerfile.smtp-graph`](../Dockerfile.smtp-graph) bauen. Erst nach Bereitstellung der neuen Images die aktualisierte Basis-Compose-Datei und den Zusatz auf dem Host verwenden:

```sh
cd /opt/stacks/helfertool
docker compose -f compose.yaml -f compose.smtp-oauth.yaml config --quiet
docker compose -f compose.yaml -f compose.smtp-oauth.yaml pull

# Gibt einen Device-Code und die Microsoft-Anmeldeseite aus.
docker compose -f compose.yaml -f compose.smtp-oauth.yaml run --rm --no-deps smtp-relay login

docker compose -f compose.yaml -f compose.smtp-oauth.yaml up -d
docker compose -f compose.yaml -f compose.smtp-oauth.yaml ps
docker compose -f compose.yaml -f compose.smtp-oauth.yaml exec helfertool \
  /usr/local/bin/helfertool manage sendtestemail <Testempfaenger>
docker compose -f compose.yaml -f compose.smtp-oauth.yaml logs --tail 100 smtp-relay
```

Die ausgegebene Microsoft-Seite im Browser oeffnen, den Code eingeben und als `OAUTH_USERNAME` anmelden, einschliesslich MFA. Bei Erfolg speichert MSAL die Sitzung im benannten Volume `smtp-relay-tokens`. Das Relay verweigert den Versand mit einem anderen Konto. Kein Client Secret oder Kontopasswort in `.env` eintragen.

Fuer alle weiteren Compose-Befehle beide Dateien angeben. Bei Bind-Storage zusaetzlich `-f compose.bind-storage.yaml` verwenden. In Dockge die Service-, Environment-, Netzwerk- und Volume-Eintraege des Overrides in die Basisdatei **zusammenfuehren**, nicht zwei `services:`- oder `helfertool:`-Bloecke aneinanderhaengen. Die einmalige Anmeldung per CLI bleibt erforderlich.

Die aktive Absenderadresse ohne das Quoting-Problem des Helfertool-Wrappers pruefen:

```sh
printf '%s\n' 'from django.conf import settings; print(settings.DEFAULT_FROM_EMAIL)' |
  docker compose -f compose.yaml -f compose.smtp-oauth.yaml exec -T helfertool \
  /usr/local/bin/helfertool manage shell
```

### Automatischer Betrieb und Grenzen

* **Normalbetrieb:** Token-Erneuerung erfolgt automatisch ueber MSAL. Ein Container-Neustart erfordert bei erhaltenem Cache keine Anmeldung. Sitzungswiderruf, Consent-Entzug oder Tenant-Richtlinien koennen eine erneute Browser-/MFA-Anmeldung verlangen. Dann den `run ... login`-Befehl wiederholen. Delegierte Anmeldung garantiert keinen dauerhaft unbeaufsichtigten Betrieb.
* **Fehler:** Ohne nutzbare Sitzung oder bei voruebergehenden Graph-Fehlern antwortet das Relay mit SMTP `451`. Fehlende Send-As-Rechte ergeben `550`, unzulaessige Von-Adressen `553`. Die Anwendung erhaelt einen Fehler statt einer scheinbar erfolgreichen Zustellung.
* **Keine lokale Warteschlange:** SMTP `250` wird erst nach Graph `202 Accepted` zurueckgegeben. Bei Fehlern muss Helfertool beziehungsweise der Aufrufer erneut senden. Nach einem Netzwerk-Timeout kann die Annahme durch Graph unklar sein; ein erneuter Versand kann dann doppelt zustellen.
* **Groessenlimit:** Die komplette SMTP-Nachricht inklusive MIME-/Anhangskodierung darf hoechstens **3'000'000 Bytes** gross sein. Zusaetzlich wird der tatsaechlich Base64-kodierte Graph-Request auf **4'000'000 Bytes** begrenzt. Groessere Nachrichten erhalten SMTP `552`; Upload-Sessions fuer grosse Anhaenge sind nicht implementiert.
* **Inhalte:** MIME-Text, HTML und Anhaenge bleiben erhalten. Graph-Empfaenger werden mit dem SMTP-Envelope abgeglichen; nicht sichtbare Envelope-Empfaenger werden als Bcc behandelt, nicht als sichtbare To-/Cc-Adressen.
* **Pruefung:** `healthy` bestaetigt nur den lokalen SMTP-Dienst, nicht die OAuth-Sitzung oder Send-As-Rechte. Graph `202` bedeutet Annahme, nicht abgeschlossene Zustellung. Testnachricht im Empfaengerpostfach und gegebenenfalls im Exchange Message Trace kontrollieren.
* **Netzwerk:** Kein Host-Port wird veroeffentlicht. Nur Helfertool und Relay teilen `smtp-internal`; das separate `smtp-egress` erlaubt ausgehendes HTTPS zu Entra/Graph auf TCP 443. Lokal gibt es keine SMTP-Anmeldung und kein TLS; keine untrusted Container anschliessen oder Portfreigaben ergaenzen.
* **Token-Schutz:** Das Relay laeuft unprivilegiert. `/data` ist nur fuer seinen Benutzer zugaenglich; der MSAL-Cache liegt unverschluesselt mit restriktiven Dateirechten im Volume. Er enthaelt Refresh-/Access-Tokens und muss wie ein Passwort behandelt werden. Docker-Administratoren koennen darauf zugreifen.
* **Backup:** Die bestehenden Host-Backupskripte sichern weder das Token-Volume noch laden sie den Relay-Zusatz. Den Cache separat geschuetzt sichern oder nach einem Verlust erneut anmelden. Keine Cache-Dateien committen, versenden oder in Logs ausgeben. Kein `down -v` verwenden.

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

Tests auf Linux mit Bash, Python 3 und GNU tar. Die Graph-Tests benoetigen die Relay-Abhaengigkeiten; die Compose-Tests benoetigen Docker Compose v2, aber keine laufende Container-Engine. In einer aktivierten Python-Virtualenv:

```sh
python3 -m pip install -r relay/requirements.txt
python3 -m unittest discover -s tests -v
```

## Weiterfuehrend

- [Backup, Restore und Datenpfadwechsel](Backup.md)
- [Lokaler HTTPS-Test auf Windows mit Podman](Local-HTTPS.md)
- [Offizielles Admin-Handbuch](https://docs.helfertool.org/admin/index.html)
