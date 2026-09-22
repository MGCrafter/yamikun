# Einrichtung & Konfiguration

[Zurück zur README](../README.md)

## Server-übergreifendes Verhalten

Der Bot ist für mehrere Discord-Server gedacht.

Global pro User gespeichert werden:

- Coins
- XP und Level
- Karten-Inventare
- Booster-Packs
- Daily/Shop-Effekte
- Freundschaften und Friendship-XP
- Achievement-Freischaltungen

Pro Server gespeichert werden:

- Channels
- Rollen
- WebPanel-/Feature-Einstellungen
- getrackte Spiele
- Ticket-Konfiguration
- Audit-/Welcome-/Boost-/ReactionRole-Einstellungen

## Voraussetzungen lokal

- Python 3.12 empfohlen (wie im Docker-Image)
- Node.js 22
- npm
- Discord Developer Portal Zugriff

Empfohlen mit venv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Frontend installieren:

```bash
cd frontend
npm ci
npm run build
```

## Discord Developer Portal

1. Discord Developer Portal öffnen: https://discord.com/developers/applications
2. New Application erstellen.
3. Unter Bot einen Bot anlegen und Token kopieren.
4. Unter Bot → Privileged Gateway Intents aktivieren:
   - Message Content Intent
   - Server Members Intent
5. Optional für Spiel-/Presence-Karten:
   - Presence Intent aktivieren
   - `PRESENCE_INTENT=1` setzen
6. Unter OAuth2 → URL Generator:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions mindestens:
     - Send Messages
     - Manage Messages
     - Use Application Commands
     - Manage Roles, falls Reaction Roles/Auto-Rollen genutzt werden
     - Manage Channels und Move Members für das Join-to-Create-Voice-System
     - Manage Threads/Create Private Threads für Tickets

## Konfiguration

Kopiere die Vorlage:

```bash
cp .env.example .env
```

Wichtige Variablen:

```env
DISCORD_TOKEN=
GUILD_ID=
PRESENCE_INTENT=1
WEB_ENABLED=1
WEB_BASE_URL=https://deine-domain.example
OAUTH_CLIENT_ID=
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
OAUTH_CLIENT_SECRET=
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_OWNER_IDS=

# Optional; Standardwerte für schnelle Discord-Kartenbilder
CARD_IMAGE_WEBP_QUALITY=82
CARD_IMAGE_MAX_DIMENSION=1200
CARD_IMAGE_ANIMATED_MAX_DIMENSION=960
CARD_IMAGE_MAX_FRAMES=80
CARD_IMAGE_MAX_BYTES=6291456
```

`GUILD_ID` ist optional. Wenn gesetzt, werden Slash-Commands sofort auf diesem Server synchronisiert. Ohne `GUILD_ID` synchronisiert Discord global, was bis zu etwa einer Stunde dauern kann.

Hochgeladene Sammel- und Yami-Karten werden automatisch als kompakte WebP-Dateien gespeichert. Zu große Bilder werden verkleinert, lange Animationen auf höchstens 80 Frames begrenzt und Animationen über dem Dateilimit als schnelles Standbild abgelegt. Beim ersten Start nach dem Update migriert der Bot vorhandene lokale PNG-, JPEG-, GIF- und übergroße WebP-Karten unter `/data/static/` und aktualisiert deren URLs in der Datenbank. Die `CARD_IMAGE_*`-Variablen sind optional; ohne Einträge gelten die oben gezeigten Standardwerte.

## WebPanel/OAuth

Für das WebPanel brauchst du im Discord Developer Portal unter OAuth2 → Redirects:

```text
<WEB_BASE_URL>/callback
```

Beispiel:

```text
https://yumikun.example/callback
```

`WEB_BASE_URL` muss öffentlich erreichbar sein, damit Discord OAuth und hochgeladene Bilder funktionieren.

Zugriff im Admin-Panel bekommt, wer auf einem Server mit dem Bot die Berechtigung „Server verwalten“ hat. Wenn `WEB_OWNER_IDS` gesetzt ist, dürfen nur diese Discord-User-IDs Karten hoch-/runterladen; normale Admins können weiterhin ansehen und serverbezogene Admin-Funktionen nutzen. Globale Guthabenänderungen (auch `/level coins`) und das Löschen fremder Inventarkarten sind immer auf `WEB_OWNER_IDS` beschränkt; bei leerer Liste sind diese Aktionen gesperrt.

## Lokal starten

Backend/Bot:

```bash
. .venv/bin/activate
python bot.py
```

Frontend nur entwickeln:

```bash
cd frontend
npm run dev
```

Gebautes Frontend erzeugen:

```bash
cd frontend
npm run build
```

## Troubleshooting

### Bot startet nicht wegen Intents

Im Discord Developer Portal prüfen:

- Message Content Intent aktiv
- Server Members Intent aktiv
- Presence Intent nur nötig, wenn `PRESENCE_INTENT=1` gesetzt ist

### Slash-Commands erscheinen nicht

- Für sofortige Tests `GUILD_ID` setzen.
- Ohne `GUILD_ID` kann Discord globale Commands erst nach bis zu etwa einer Stunde anzeigen.
- Bot muss mit Scope `applications.commands` eingeladen sein.

### WebPanel Login schlägt fehl

Prüfen:

- `WEB_ENABLED=1`
- `WEB_BASE_URL` korrekt und öffentlich erreichbar
- Discord OAuth Redirect exakt `<WEB_BASE_URL>/callback`
- `OAUTH_CLIENT_ID` und `OAUTH_CLIENT_SECRET` korrekt
- Browser-Cookies nicht blockiert

### Uploads/Bilder funktionieren nicht

Prüfen:

- `WEB_BASE_URL` ist öffentlich erreichbar
- `/data` ist persistent gemountet
- `static/` bzw. `/data/static/` ist beschreibbar
- Dateityp ist PNG, JPG, GIF oder WebP

### CapRover verliert Daten nach Deploy

Dann fehlt fast immer das Persistent Directory auf `/data`. Ohne `/data`-Mount verschwindet SQLite-Datenbestand beim Container-Wechsel.
