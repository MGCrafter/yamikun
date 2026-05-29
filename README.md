# Oaken Tower Hash-Code Discord Bot

Ein Discord-Bot für die Oaken-Tower-Community mit mehreren Modulen:

1. **Auto-Delete** (`/oaken`) — löscht in aktivierten Channels automatisch den
   alten Oaken-Tower-Code eines Users, sobald derselbe User einen neuen postet.
2. **Leveling** (`/rank`, `/leaderboard`, `/level`) — XP durch Nachrichten &
   Voice, Level-Aufstiege mit Coin-Belohnung.
3. **Economy** (`/daily`, `/pay`) — tägliche Belohnung mit Streak, Coins überweisen.
4. **Gambling** (`/coinflip`, `/blackjack`, `/slots`) — Glücksspiele mit der
   Coin-Währung.
5. **Shop** (`/shop`, `/buy`) — Coins gegen temporäre Boosts (Glücksbringer, XP-Boost).
6. **Profil** (`/profile`, `/setbio`) — Statistik-Seite inkl. Spiel-Statistiken.
7. **Social** (`/friend`) — Freundesliste mit Anfragen und Friendship-Level.
8. **Interactions** (`/hug`, `/pat`, `/kiss`, `/slap`, `/highfive`) — GIF-Aktionen.
9. **LFG** (`/lfg`) — Gruppensuche mit Join-Buttons und opt-in Ping-Rolle.
10. **Announcer** (`/announce`) — neue Beiträge überwachter Quellen (YouTube/RSS)
    in einen Announce-Channel posten.
11. **Moderation** (`/purge`) — Nachrichten massenweise löschen.
12. **Booster / Yami-Karten** (`/booster`) — Sammelkarten über Booster-Packs (mit Coins gekauft).

Der Code ist in Cogs aufgeteilt: `bot.py` (Loader) lädt die Module unter `cogs/`;
`db.py` kapselt die SQLite-Datenbank (`bot.db`). Die Münz-Währung wird mit dem
Server-Emoji `:YamiToken:` dargestellt (Fallback 🪙).

## Voraussetzungen

- Python 3.11+
- Ein Discord-Account mit Rechten, einen Bot zu erstellen

## 1. Bot im Discord Developer Portal anlegen

1. Öffne das [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → Namen vergeben → **Create**.
3. Links auf **Bot** → **Add Bot** (falls nötig) bestätigen.
4. Unter **Bot** den Token via **Reset Token** anzeigen lassen und kopieren.
   Diesen Token brauchst du gleich für `DISCORD_TOKEN`. **Niemals öffentlich teilen.**

### Message Content Intent aktivieren

Der Bot muss den Inhalt von Nachrichten lesen können, um Codes zu erkennen und
Nachrichten-XP zu vergeben:

1. Im Developer Portal unter **Bot** → Abschnitt **Privileged Gateway Intents**.
2. **Message Content Intent** einschalten und speichern.

### Optional: Sammelkarten-Rewards (Presence Intent)

Nur nötig für die **Sammelkarten fürs Spielen** (`/cards`). Dafür muss der Bot
sehen, welches Spiel jemand spielt:

1. Im Developer Portal **Presence Intent** **und** **Server Members Intent** aktivieren.
2. In der `.env` `PRESENCE_INTENT=1` setzen und den Bot neu starten.

Ohne diese Variable bleibt das Karten-Tracking inaktiv (der Rest des Bots läuft
normal). Ist `PRESENCE_INTENT=1` gesetzt, aber die Intents im Portal **nicht**
aktiviert, startet der Bot nicht — dann die Portal-Einstellung nachholen.

## 2. Bot einladen

Erzeuge eine Einladungs-URL mit den nötigen Rechten:

1. Im Developer Portal unter **OAuth2** → **URL Generator**.
2. **Scopes:** `bot` und `applications.commands`.
3. **Bot Permissions:** `Send Messages`, `Manage Messages`, `Use Application Commands`.
   Optional **`Manage Roles`** — nur nötig, damit sich Mitglieder per `/lfg role`
   selbst die LFG-Ping-Rolle geben können (die Bot-Rolle muss dann über der
   LFG-Rolle stehen).
4. Generierte URL öffnen und den Bot auf deinen Server einladen.

## 3. Installation

```bash
pip install -r requirements.txt
```

## 4. Token konfigurieren

Variante A — Umgebungsvariable (fish-Shell):

```fish
set -x DISCORD_TOKEN "dein-token-hier"
```

Variante B — `.env`-Datei (empfohlen, nutzt `python-dotenv`):

```bash
cp .env.example .env
```

Dann `.env` öffnen und den Token bei `DISCORD_TOKEN=` eintragen.

### Optional: Commands sofort sichtbar machen

Ohne weitere Konfiguration werden die Slash-Commands **global** registriert —
das kann bei Discord bis zu **~1 Stunde** dauern, bis sie überall erscheinen.

Setzt du zusätzlich `GUILD_ID` (deine Server-ID), werden die Commands sofort auf
diesem Server registriert — ideal zum Testen:

```fish
set -x GUILD_ID "deine-server-id"
```

oder in der `.env` die Zeile `GUILD_ID=` einkommentieren und füllen.
(Server-ID: Discord → Servereinstellungen → Erweitert → Entwicklermodus an,
dann Rechtsklick auf den Server → **ID kopieren**.)

## 5. Bot starten

```bash
python bot.py
```

## 6. Im Channel aktivieren

Führe im gewünschten Channel den Slash-Command aus:

```
/oaken on
```

Ab jetzt löscht der Bot dort den jeweils vorherigen Code jedes Users, sobald
dieser einen neuen postet.

## Befehle

> **`/help`** zeigt alle Befehle interaktiv in Discord (Kategorie per Dropdown wählen).
>
> „Mods" = Berechtigung **Kanäle verwalten** (bzw. **Nachrichten/Rollen verwalten**
> beim jeweiligen Befehl) oder Administrator. Die Einstellwerte stehen jeweils als
> Konstanten oben in der zugehörigen Datei unter `cogs/` und sind leicht anpassbar.

### Auto-Delete (`/oaken`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/oaken on` / `off` / `status` | Auto-Delete im Channel an/aus/Status (Status zeigt auch die aktuelle Runde) | alle |
| `/oaken newgame` / `endgame` | 1v1-Spiel mit Rundenzählung starten / beenden | alle |
| `/oaken reset` | Vergisst gespeicherte Code-IDs (löscht nichts) | Mods |

Ein Code ist ein zusammenhängender Block aus **≥ 200** Base64-Zeichen
(`A–Z a–z 0–9 + / =`). Der alte Code eines Users wird gelöscht, sobald derselbe
User einen neuen postet; Codes anderer bleiben unangetastet.

**1v1-Rundenzählung:** Nach `/oaken newgame` antwortet der Bot auf jeden Code mit
„🎮 Runde X — Code von @user". Eine Runde steigt erst, wenn **beide** Spieler einen
neuen Code gepostet haben — so ist immer klar, wer in welcher Runde dran ist.

### Leveling (`/rank`, `/leaderboard`, `/level`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/rank [user]` | Level, XP-Fortschritt und Coins | alle |
| `/leaderboard` | Top 10 nach XP | alle |
| `/title list / set / clear` | XP-Titel anzeigen/wählen (durch Level freischaltbar, im Profil sichtbar) | alle |
| `/level setchannel #channel` | Channel für Level-Up-Meldungen | Mods |
| `/level give @user <coins>` | Coins vergeben/entziehen | Mods |

Als Leveling-Belohnung dienen **Titel** (statt Rollen): Sie werden durch Level
freigeschaltet, mit `/title set` gewählt und personalisieren das `/profile`.
Die Titel-Stufen stehen in `cogs/titles.py`.

- **Nachrichten:** 15–25 XP, max. 1× pro 60 s. **Voice:** 5 XP/Min (nicht AFK,
  ≥ 2 Personen, nicht taub). **Level-Kurve:** `5·level² + 50·level + 100`.
- **Coins beim Level-Up:** `100 × neues Level`. Level-Up-Meldungen nur, wenn
  `/level setchannel` gesetzt ist.

### Economy (`/daily`, `/pay`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/daily` | Tägliche Coin-Belohnung mit Streak | alle |
| `/pay @user <betrag>` | Coins an jemanden überweisen (1:1, keine Gebühr) | alle |

- **Daily:** alle 24 h; Streak +1 pro Tag, mehr als 48 h Pause setzt sie zurück.
  Belohnung = `10 × Streak` (max 500) **+100** alle 7 Streak-Tage.

### Gambling (`/coinflip`, `/blackjack`, `/slots`)

| Command | Beschreibung |
|---|---|
| `/coinflip <head/tail> <einsatz>` | Münzwurf, 48 % Gewinnchance, Gewinn 1:1 |
| `/blackjack <einsatz>` | Blackjack gegen den Dealer (Hit/Stand/Double/Split, Blackjack zahlt 3:2) |
| `/slots <einsatz>` | 3-Walzen-Slot, nur 3 Gleiche zahlen (Jackpot `:YamiToken:` ×100), RTP ~90 % |

Einsatz jeweils **1–10.000**, nie mehr als der Kontostand. Spiel-Statistiken
fließen ins `/profile`.

### Shop (`/shop`, `/buy`)

| Command | Beschreibung |
|---|---|
| `/shop` | Zeigt kaufbare Items |
| `/buy <item>` | Kauft ein Item |

- **🍀 Glücksbringer** (20.000): erhöhte Gewinnchance für die nächsten 5
  Coinflip-/Slots-Spiele (Coinflip 65 %, Slots stärker gewichtet).
- **⚡ XP-Boost** (10.000): doppelte XP (Nachrichten & Voice) für 60 Minuten.

### Profil (`/profile`, `/setbio`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/profile [user]` | Avatar, Level + XP-Balken, Coins, Rang, Spiel-Statistiken, Titel, Ehen, Bio | alle |
| `/setbio <text>` | Eigene Bio setzen (max. 200 Zeichen, leer = löschen) | alle |
| `/setcolor <hex>` | Profil-Akzentfarbe wählen (`#FF8800`; `reset` = Rollenfarbe) | alle |

### Social (`/friend`)

| Command | Beschreibung |
|---|---|
| `/friend add @user` | Freundschaftsanfrage schicken |
| `/friend accept @user` | Anfrage annehmen |
| `/friend remove @user` | Freundschaft/Anfrage entfernen |
| `/friend requests` | Offene eingehende Anfragen |
| `/friend list [user]` | Freundesliste mit Friendship-Level |
| `/friend level @user` | Euer gemeinsames Friendship-Level |
| `/marry @user` | Heiratsantrag (mit Bestätigung & Hochzeits-GIF); mehrere Ehen erlaubt |
| `/divorce @user` | Scheidung |
| `/marriages [user]` | Zeigt die Ehen einer Person |

Friendship-Level = Freundschafts-XP ÷ 100; **+10 XP** pro Interaction. Ehen werden
auch im `/profile` angezeigt.

### Interactions

`/hug`, `/pat`, `/kiss`, `/slap`, `/highfive` `@user` — postet ein zufälliges
GIF (via **nekos.best**, ohne API-Key), zählt die Interaktionen und gibt
Freundschafts-XP.

### LFG — Looking for Group (`/lfg`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/lfg start <size> <beschreibung> <channel> [rolle]` | Gruppensuche mit Join/Leave-Buttons. Pingt die gewählte `rolle` (sonst die LFG-Rolle), zeigt den Voice-Channel, läuft nach 1 h ab; löst der Host auf, wird der Post gelöscht | alle |
| `/lfg role` | Selbst für LFG-Pings an-/abmelden | alle |
| `/lfg setrole @rolle` | Legt die LFG-Ping-Rolle fest | Rollen verwalten / Admin |

`/lfg role` braucht beim Bot die Berechtigung **Rollen verwalten** (Bot-Rolle über
der LFG-Rolle). Das **Pingen** funktioniert auch ohne.

### Announcer (`/announce`, nur Mods)

| Command | Beschreibung |
|---|---|
| `/announce channel #channel` | Setzt den Announce-Channel |
| `/announce add <quelle> [label]` | Überwacht eine Quelle (YouTube-URL/@Handle/Kanal-ID **oder** RSS-Feed-URL) |
| `/announce list` / `remove <id>` | Quellen anzeigen / entfernen |
| `/announce post <link> [text]` | Link manuell in den Announce-Channel posten |

- **YouTube** läuft automatisch über den offiziellen RSS-Feed (kein API-Key).
- **TikTok/Instagram** haben keine kostenlose API → RSS-Bridge-URL (RSSHub/RSS.app)
  per `/announce add` hinterlegen oder per `/announce post` manuell teilen.
- Prüfung alle **5 Minuten**; beim Hinzufügen werden alte Beiträge **nicht**
  nachgepostet.

### Moderation (`/purge`, `/say`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/purge <anzahl> [user]` | Löscht 1–100 Nachrichten (optional nur von einem User) | Nachrichten verwalten / Admin |
| `/say <text> [channel]` | Lässt den Bot eine Nachricht schreiben (kein @everyone; wird geloggt) | Nachrichten verwalten / Admin |

Discord erlaubt Massen-Löschen nur für Nachrichten **jünger als 14 Tage**.

### Fun & Sonstiges

| Command | Beschreibung |
|---|---|
| `/8ball <frage>` | Antwort der magischen Miesmuschel |
| `/insult [@user]` | Zufällige, harmlose deutsche Beleidigung |
| `/whoisguilty <verdächtige>` | Bot ermittelt zufällig den „Schuldigen" aus den gepingten Personen |
| `/existential [stil]` | Cursed Weisheiten / Fake-deep Quotes / philosophischer Unsinn |
| `/summondemon` | Beschwört Yami — zufällig gnädig (`:YamiLuv:`) oder erzürnt (Cooldown) |

### Spiel-Sammelkarten (`/gamecards`, `/gamecard`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/gamecards [user]` | Zeigt die erspielten Sammelkarten | alle |
| `/gamecard <karte>` | Zeigt eine einzelne Karte (Bild + Seltenheit) | alle |
| `/gamereward addgame <spiel>` | Spiel hinzufügen, das Karten gibt | Server verwalten / Admin |
| `/gamereward removegame <spiel>` / `listgames` | Spiel entfernen / alle anzeigen | Server verwalten / Admin |
| `/gamereward addcard <spiel> <name> <seltenheit> <bild-url>` | Karte für ein Spiel anlegen (Bild-URL ist Pflicht) | Server verwalten / Admin |
| `/gamereward removecard <karte>` / `listcards <spiel>` | Karte entfernen / Karten eines Spiels anzeigen | Server verwalten / Admin |
| `/gamereward setchannel [#channel]` | Channel für Karten-Drop-Meldungen (ohne Angabe: DMs) | Server verwalten / Admin |

**Karten sind pro Spiel:** Wer ein Spiel spielt, erhält nur dessen Karten. Jede
Karte wird manuell angelegt und braucht eine **Bild-URL**. Hat ein Spiel keine
Karten, droppt nichts (es gibt kein eingebautes Set).

Fürs Spielen konfigurierter Spiele gibt es **1 Karte pro 30 Min Spielzeit**, max.
**12 Karten/Tag**. 6 Seltenheiten (Common→Mythic), zufällige gewichtete Drops.
**Erfordert das Presence Intent** (siehe unten).

### Booster & Yami-Karten (`/booster`, `/yamicard`)

Zweites, eigenständiges Kartensystem (getrennter Pool & Sammlung):

| Command | Beschreibung | Wer? |
|---|---|---|
| `/booster buy <typ> [anzahl]` | Booster-Packs mit Coins kaufen | alle |
| `/booster open <typ>` | Ein Pack öffnen → zufällige Karten | alle |
| `/booster packs` | Ungeöffnete Packs anzeigen | alle |
| `/booster collection [user]` | Yami-Karten-Sammlung | alle |
| `/booster card <karte>` | Eine Yami-Karte ansehen | alle |
| `/yamicard add <name> <seltenheit> <bild-url>` | Yami-Karte anlegen (Bild-URL Pflicht) | Server verwalten / Admin |
| `/yamicard remove <karte>` / `list` | Karte entfernen / alle anzeigen | Server verwalten / Admin |

Pack-Tiers (in `cogs/booster.py` anpassbar): **Standard** (2.000 Coins, 5 Karten) und
**Premium** (5.000 Coins, 5 Karten, bessere Chancen auf seltene Karten). Packs werden
mit Coins gekauft, sammeln sich an und werden mit `/booster open` geöffnet; die Karten
landen in der separaten Yami-Karten-Sammlung. Auch im `/shop` gelistet.

## Persistenz

- **Auto-Delete:** aktivierte Channels und gemerkte Code-Message-IDs in
  `config.json`.
- **Alles andere:** XP/Level/Coins, Daily-Streaks, Shop-Effekte, Spiel-Statistiken,
  Freundschaften, Interaction-Zähler, Channel-/Rollen-Einstellungen und überwachte
  Quellen in der SQLite-Datenbank `bot.db`.

Beide werden beim ersten Start automatisch angelegt, überleben Neustarts und sind
in der `.gitignore` ausgeschlossen (enthalten Server-/User-Daten).

## Dauerbetrieb (systemd)

Auf dem Zielsystem läuft der Bot als systemd-User-Service `oaken-bot.service`
(Auto-Restart bei Absturz, Autostart beim Booten). Nützliche Befehle:

```bash
systemctl --user status oaken-bot      # Status
systemctl --user restart oaken-bot     # nach Code-Änderungen neu starten
journalctl --user -u oaken-bot -f      # Live-Logs
```

Nach Änderungen an `bot.py` oder den Cogs jeweils `systemctl --user restart
oaken-bot` ausführen.
