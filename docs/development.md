# Entwicklung

[Zurück zur README](../README.md)

## Checks

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
npm ci --prefix frontend
bash scripts/check.sh
```

Die Tests verwenden temporäre Datenbanken und simulierte Antworten. Der Check
kompiliert Python, führt `pytest` aus, prüft TypeScript und baut das Frontend.
Der GitHub-Workflow verwendet Python 3.12 und Node.js 22 wie das Dockerfile.

## Frontend mit Live-Reload

```bash
npm run dev --prefix frontend
```

Vite läuft auf Port `5173` und leitet API-, Login- und Asset-Anfragen an das lokale
Preview-Backend auf Port `8099` weiter.

Für eine Vorschau mit einer **bereits vorhandenen lokalen Datenbank**:

```bash
source .venv/bin/activate
python dev_panel.py
```

Das Skript kopiert `bot.db` inklusive vorhandener WAL-/SHM-Dateien nach
`/tmp/devpanel/` und arbeitet dort mit Dummy-Discord-Objekten. Es startet keinen
Discord-Bot. Auf einer frischen Installation ohne Serverdaten gibt es noch keine
Server anzuzeigen. Das gebaute Panel ist unter `http://127.0.0.1:8099/app` erreichbar.

Die Vorschau überspringt OAuth und bindet nur an `127.0.0.1`; sie ist ein lokales
Entwicklungswerkzeug und wird nicht ins Docker-Image übernommen. Bei einer gerade
beschriebenen Datenbank besser mit einer konsistenten Sicherung arbeiten.

## Ablage im Projekt

- `docs/archive/`: frühere Spezifikationen und Anleitungen, teilweise historisch.
- `docs/community/`: Texte für Community-Ankündigungen.
- `docs/design/`: erhaltene Designstudien.
- `.local/deployments/`: lokale CapRover-Tarballs, nach Datum und Uhrzeit.
- `.local/archives/`: alte Design-Exporte.
- `.local/notes/`: persönliche lokale Arbeitsnotizen.
- `backups/`: lokale Datenbank-Sicherungen; ältere Einzeldateien unter `legacy/`.

`.local/` und `backups/` werden nicht eingecheckt. Generierte Dateien wie
`frontend/dist/`, `frontend/vite.config.js`, `frontend/vite.config.d.ts`,
`*.tsbuildinfo`, `node_modules/` und Python-Caches bleiben ebenfalls lokal.

## Aufbau

`bot.py` lädt die Discord-Module unter `cogs/`. Der Einstieg zum Webserver ist
`cogs/webpanel.py`; wiederverwendbare Routen, Middleware und Bildverarbeitung
liegen unter `webpanel/`. `twitch_chat/` enthält die Twitch-Chat-Verarbeitung.
Das Frontend wird aus `frontend/` gebaut und anschließend vom selben Python-Prozess
ausgeliefert. `db.py` verwaltet SQLite und die Migrationen beim Start.
