[[_TOC_]]

# Lokaler HTTPS-Test mit Podman

Helfertool verwendet bei `DEBUG=False` sichere Cookies und benoetigt HTTPS fuer die Anmeldung. CSRF-Schutz und sichere Cookies bleiben bei diesem Testaufbau aktiv. Der lokale Caddy-Proxy ist nur an `127.0.0.1` gebunden; `localhost` muss in `HELFERTOOL_ALLOWED_HOSTS` stehen.

## Start und Betrieb

Im Projektverzeichnis ausfuehren:

```powershell
podman compose -f compose.yaml -f compose.local-https.yaml up -d --wait --wait-timeout 180
```

Die Anwendung ist unter `https://localhost:18443/` erreichbar. `http://localhost:18080/` leitet dorthin um. Helfertool selbst hat in dieser Konfiguration keinen veroeffentlichten HTTP-Port. Caddy uebermittelt das HTTPS-Schema und den urspruenglichen Host an Django.

Der nginx im Helfertool-Image entfernt den Port aus dem Host-Header. Deshalb bindet die lokale Erweiterung `uwsgi.local-https.params` ein: Sie erhaelt den von nginx normalisierten Host und ergaenzt den festen externen Port `18443`, damit Django Origin- und Referer-Pruefungen sowie absolute URLs korrekt verarbeitet. Bei einer Aenderung des HTTPS-Ports auch diese Datei und die Weiterleitung in `Caddyfile.local` anpassen. Diese Datei nicht fuer den Produktionsbetrieb auf Port 443 verwenden.

Bei weiteren Compose-Aufrufen immer beide `-f`-Argumente verwenden, beispielsweise:

```powershell
podman compose -f compose.yaml -f compose.local-https.yaml ps
podman compose -f compose.yaml -f compose.local-https.yaml down
```

Ein Aufruf nur mit der Basiskonfiguration aktiviert wieder den direkten HTTP-Port und kann mit dem lokalen Proxy kollidieren.

## Lokalem Zertifikat vertrauen

Caddy erzeugt eine lokale Zertifizierungsstelle und speichert sie im benannten Volume `local-https-data`. Ein Browser vertraut dieser CA nicht automatisch. Folgende Befehle exportieren ausschliesslich das oeffentliche CA-Zertifikat und nehmen es fuer den aktuellen Windows-Benutzer in die vertrauenswuerdigen Stammzertifizierungsstellen auf:

```powershell
podman compose -f compose.yaml -f compose.local-https.yaml cp local-https:/data/caddy/pki/authorities/local/root.crt ./config/local-https-root.crt
Import-Certificate -FilePath ./config/local-https-root.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Dies ist eine bewusste Aenderung des Zertifikatsvertrauens. Nur die eigene lokale CA importieren; deren privater Schluessel bleibt im Caddy-Volume und darf nicht weitergegeben werden. Browser danach vollstaendig neu starten, falls das Zertifikat noch nicht erkannt wird. Bei Firefox kann je nach Konfiguration ein separater Import erforderlich sein.

Die Anwendung neu unter `https://localhost:18443/` oeffnen und das Anmeldeformular neu laden. Alte Formulare und Cookies aus dem vorherigen HTTP-Test nicht weiterverwenden.

Zum Entfernen der lokalen CA aus dem Windows-Vertrauensspeicher:

```powershell
$certificate = Get-PfxCertificate -FilePath ./config/local-https-root.crt
Remove-Item -LiteralPath "Cert:\CurrentUser\Root\$($certificate.Thumbprint)"
```

Die CA ist nicht in den bestehenden Anwendungsbackups enthalten. Wird ihr Volume geloescht, erstellt Caddy eine neue CA; deren Zertifikat muss erneut vertraut werden. Keine Volumes mit Anwendungsdaten loeschen.

## Produktion

Diese Compose-Erweiterung und die lokale CA sind nur fuer lokale Tests bestimmt. Fuer `helfer.hgis.ch` einen produktiven Reverse Proxy mit oeffentlich vertrauenswuerdigem Zertifikat verwenden und den Domainnamen in den erlaubten Hosts eintragen. Das Domain-Root ist dem Unterpfad `hgis.ch/helfer` vorzuziehen; ein Unterpfad erfordert eine gesonderte Pruefung der URL-, Static- und Cookie-Pfade.