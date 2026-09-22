# Deployment & Updates

[Zurück zur README](../README.md)

Yamikun läuft als ein Container: `discord.py` betreibt den Bot, `aiohttp` liefert
die API und das gebaute React-Webpanel aus. CapRover baut direkt aus diesem
Repository; ein lokal gebautes `frontend/dist` muss nicht eingecheckt werden.

## 1. CapRover-App vorbereiten

Für eine bestehende Installation dieselbe App und denselben persistenten
Datenspeicher weiterverwenden. Der Wechsel von Tarball zu GitHub ändert nur die
Quelle des Builds.

| Einstellung | Wert |
| --- | --- |
| Container HTTP Port | `8080` |
| Persistent Directory / Container-Pfad | `/data` |
| Instanzen | `1` |
| Captain Definition File | `captain-definition` |

Bei einer neuen App einen persistenten Speicher auf `/data` anlegen. Dort liegen
SQLite, Konfiguration und hochgeladene Kartenbilder. Bei einer bestehenden App
vor dem Wechsel prüfen, dass genau der bisherige Speicher weiter gemountet ist.

Umgebungsvariablen in **App Configs → Environmental Variables** eintragen:

```dotenv
DISCORD_TOKEN=<Discord-Bot-Token>
WEB_ENABLED=1
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_BASE_URL=https://deine-domain.example
OAUTH_CLIENT_ID=<Discord-Client-ID>
OAUTH_CLIENT_SECRET=<Discord-Client-Secret>
WEB_OWNER_IDS=<deine-Discord-User-ID>
```

`DATA_DIR=/data` ist bereits im Dockerfile gesetzt. HTTPS für die öffentliche
Domain aktivieren. Im Discord Developer Portal den Redirect
`https://deine-domain.example/callback` eintragen. Weitere Variablen, Intents und
Berechtigungen: [Einrichtung](setup.md) und [`.env.example`](../.env.example).

Für Twitch Live werden `TWITCH_CLIENT_ID` und `TWITCH_CLIENT_SECRET` benötigt.
Für den Chatbot sind weitere Schlüssel und der Twitch-Redirect nötig; siehe
[Twitch-Chatbot](twitch-chat.md). Den `TWITCH_TOKEN_KEY` über Deployments hinweg
beibehalten, damit gespeicherte Tokens weiter entschlüsselt werden können.

## 2. GitHub als Deployment-Quelle verbinden

In der CapRover-App unter **Deployment → Method 3: Deploy from Github/Bitbucket/Gitlab**
die Repository-Daten setzen:

- Repository: `https://github.com/MGCrafter/yamikun.git`
- Branch: `main`
- Benutzername: `MGCrafter`
- Zugang: Für das derzeit öffentliche Repository reicht laut CapRover-Dokumentation
  ein nicht leerer Platzhalter im Passwortfeld. Bei einem privaten Repository
  stattdessen einen geeigneten Zugang bzw. einen SSH-Deploy-Key verwenden.

Konfiguration speichern. CapRover zeigt anschließend die app-spezifische
Webhook-URL an. Diese URL vertraulich behandeln und nicht in Dateien einchecken.

## 3. Automatische Updates aktivieren

In [GitHub → Repository Settings → Webhooks](https://github.com/MGCrafter/yamikun/settings/hooks)
einen Webhook anlegen:

| Feld | Wert |
| --- | --- |
| Payload URL | Webhook-URL aus der CapRover-App |
| Content type | `application/json` |
| Secret | Für den nativen CapRover-Webhook leer lassen, wie von CapRover dokumentiert |
| Events | `Just the push event` |
| Active | aktiviert |

Danach in CapRover einmal einen Build auslösen. Bei folgenden Pushes auf `main`
kann GitHub den Build automatisch starten. GitHubs „Recent Deliveries“ und die
CapRover-Deployment-Logs zeigen, ob die Verbindung funktioniert.

```text
Änderung → Commit → Push auf main → GitHub-Webhook
                                      ↓
                               CapRover Docker-Build
                                      ↓
                             Yami mit bestehendem /data
```

Die GitHub-Prüfungen laufen parallel zum nativen CapRover-Webhook. **Der Webhook
wartet nicht auf einen erfolgreichen CI-Lauf.** Deshalb vor dem Push lokal
`bash scripts/check.sh` ausführen. Für verbindliche Prüfungen vor dem Merge kann
`main` zusätzlich über GitHub-Branch-Regeln und Pull Requests geschützt werden.

Die Anleitung richtet die Verbindung nicht selbst ein; ohne gespeicherten
CapRover-Zugang und GitHub-Webhook bleibt das Deployment manuell.

Quelle: [Offizielle CapRover-Dokumentation: Deployment Methods](https://caprover.com/docs/deployment-methods.html#automatic-deploy-using-github-bitbucket-and-etc).

## 4. Nach einem Deploy prüfen

- CapRover-Build und Start-Logs prüfen; alle benötigten Cogs sollen laden.
- Öffentliche Domain und `/api/health` aufrufen.
- Discord-Login und `/help` ausprobieren.
- Vorhandene Karten, Coins und Einstellungen kontrollieren.

Der Health-Endpunkt bestätigt die Erreichbarkeit des Webservers; er ersetzt
keinen Test der Discord- oder Twitch-Verbindung.

## Manuelle Alternative: Tarball

```bash
bash scripts/make_tarball.sh
# Optional mit eigenem Basisnamen:
bash scripts/make_tarball.sh production.tar.gz
```

Die Archive liegen lokal unter:

```text
.local/deployments/YYYY-MM-DD/HH-MM-SS/production_YYYY-MM-DD_HH-MM-SS.tar.gz
```

Das Archiv unter CapRover **Deploy via Tarball** hochladen. Das Skript schließt
Zugangsdaten, Datenbanken, Uploads, lokale Archive und generierte Frontend-Dateien
aus. Frontend-Quellcode und Lockfile bleiben enthalten; Docker baut daraus die App.

## Daten & Backups

| Inhalt | Lokal | CapRover |
| --- | --- | --- |
| SQLite inklusive WAL/SHM | `bot.db*` | `/data/bot.db*` |
| Hochgeladene Bilder | `static/` | `/data/static/` |
| Laufzeitkonfiguration | `config.json` | `/data/config.json` |

Vor größeren Updates ein konsistentes SQLite-Backup erstellen:

```bash
bash scripts/backup_db.sh
# Alternativ auf einem Host mit Zugriff auf die produktive Datenbank:
bash scripts/backup_db.sh /pfad/zur/bot.db /pfad/zu/backups
```

Das Skript liegt im Repository, nicht im Produktiv-Image. Es nutzt die
SQLite-Backup-API, prüft die Sicherung und erzeugt ein Archiv mit `bot.db` und
`MANIFEST.txt`. Standardziel: `backups/YYYY-MM-DD/HH-MM-SS/`.

**Dieses Skript sichert ausschließlich die Datenbank.** Für eine vollständige
Wiederherstellung zusätzlich `static/`, gegebenenfalls `config.json` sowie die
Umgebungsvariablen und den Twitch-Verschlüsselungsschlüssel separat sichern.

Zum Wiederherstellen den Bot stoppen, den aktuellen Stand sichern und die
Datenbank aus dem Backup zurückkopieren. Veraltete WAL-/SHM-Dateien der ersetzten
Datenbank vorher zusammen mit dem alten Stand beiseitelegen. Danach den Bot
starten und prüfen. Code-Rollbacks stellen die Datenbank nicht automatisch zurück.
