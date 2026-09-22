# Oaken Tower Hash-Code Discord Bot

> Historischer Dokumentationsstand. Die aktuelle Anleitung liegt in der
> [Projekt-README](../../README.md); Installation und Deployment stehen unter
> [Einrichtung](../setup.md) und [Deployment](../deployment.md).

Ein Discord-Bot für die Oaken-Tower-Community mit mehreren Modulen:

1. **Auto-Delete** (`/oaken`) — löscht in aktivierten Channels automatisch den
   alten Oaken-Tower-Code eines Users, sobald derselbe User einen neuen postet.
2. **Leveling** (`/rank`, `/leaderboard`, `/level`) — XP durch Nachrichten &
   Voice, Level-Aufstiege mit Coin-Belohnung. Level-Up-Nachricht pro Server
   anpassbar (eigener Text mit Platzhaltern oder Standard-Embed) inkl. Ping an/aus
   — per `/level message` / `/level ping` **oder** im Webpanel.
3. **Economy** (`/daily`, `/pay`) — tägliche Belohnung mit Streak, Coins überweisen.
4. **Gambling** (`/coinflip`, `/blackjack`, `/slots`) — Glücksspiele mit der
   Coin-Währung.
5. **Shop** (`/shop`, `/buy`) — Coins gegen temporäre Boosts (Glücksbringer, XP-Boost).
6. **Profil** (`/profile`, `/setbio`, `/setfavcard`) — Statistik-Seite inkl. Spiel-Statistiken und Lieblingskarte.
7. **Social** (`/friend`) — Freundesliste mit Anfragen und Friendship-Level.
8. **Interactions** (`/hug`, `/pat`, `/kiss`, `/slap`, `/highfive`) — GIF-Aktionen.
9. **LFG** (`/lfg`) — Gruppensuche mit Join-Buttons und opt-in Ping-Rolle.
10. **Announcer** (`/announce`) — neue Beiträge überwachter Quellen (YouTube/RSS)
    in einen Announce-Channel posten.
11. **Moderation** (`/purge`, `/say`) — Nachrichten massenweise löschen, Bot sprechen lassen.
12. **Reaction Roles** (`/reactionrole`) — Mitglieder vergeben sich Rollen per Reaktion
    auf eine Nachricht; verwaltbar per Command **und** im Webpanel.
13. **Willkommensnachrichten** — begrüßt neue Mitglieder im gewählten Channel mit
    anpassbarem Text (Platzhalter `{user}`, `{server}`, `{count}`); im Webpanel einstellbar.
14. **Auto-Rollen** — vergibt neuen Mitgliedern beim Beitritt automatisch vorher
    gewählte Rollen (nur Rollen unterhalb der Bot-Rolle); komplett im Webpanel
    einstellbar (an/aus, Mehrfach-Auswahl, Hierarchie-/Rechte-Hinweise).
15. **Boost-Nachrichten** — postet eine konfigurierbare Nachricht, wenn jemand den
    Server boosted (Platzhalter `{user}`, `{username}`, `{displayName}`, `{server}`,
    `{boostCount}`, optionale Erwähnung + Bild/GIF); im Webpanel einstellbar.
16. **Audit-Log** — protokolliert Server-Ereignisse (Nachrichten, Voice, Mitglieder,
    Rollen, Channels) in die DB + optional live in einen Channel; pro Kategorie im
    Webpanel schaltbar und dort durchsuchbar.
17. **Ticket-System** (`/ticket`) — Support-Panel mit Themen-Auswahlmenü; öffnet pro
    Anliegen einen **privaten Thread** (nur Ersteller + Team), pingt die Support-Rolle,
    bietet **Übernehmen/Schließen**-Buttons und erzeugt beim Schließen ein
    **Web-Transcript** (öffentlicher Link im Discord-Stil). Im Webpanel sieht man
    **alle Tickets** und alle Transcripts. Verwaltbar per Command **und** im Webpanel.
18. **Sammelkarten** (`/gamecards`, `/trade`, `/discard`) — Karten fürs Spielen
    erspielen, mit anderen tauschen oder gegen Coins kaufen, Karten entfernen.
19. **Booster / Yami-Karten** (`/booster`) — Sammelkarten über Booster-Packs (mit
    Coins gekauft), inkl. **Spiel-Booster** + seltenes **Godpack**; Karten werden
    nacheinander aufgedeckt (rarste zuletzt).
20. **Karten-Fusion** (`/fuse`, `cogs/fusion.py`) — 5 Karten einer Seltenheit → 1
    zufällige der nächsthöheren (Common→Uncommon→…→Legendary, kein Mythic per Fusion).
21. **Webpanel** (`cogs/webpanel.py`) — Web-UI (Discord-Login):
    - **Admins:** Karten hochladen, Yami-Karten, Economy/Coins, Inventare, Reaction Roles,
      Willkommensnachrichten, **Auto-Rollen**, **Boost-Nachrichten**,
      Level-Up-Nachricht (eigener Text + Ping), Bot-Serverprofil
      (Nickname/Avatar), Nachricht senden & nachträglich bearbeiten (Text/Embed, Bilder,
      Rollen-Ping, Emojis), Audit-Log, Tickets, Spiele & Channel.
    - **Nicht-WebOwner** (wenn `WEB_OWNER_IDS` gesetzt ist): können auf der Sammelkarten-Seite
      ein **Spiel anfragen** — jeder WebOwner bekommt dann eine DM (Cooldown 5 Min pro User).
    - **Jeder User:** persönliches Dashboard (`/me`) mit eigener Sammlung, **Fusion per UI**
      und Profil/Stats. React-Frontend unter `frontend/`.

Der Code ist in Cogs aufgeteilt: `bot.py` (Loader) lädt die Module unter `cogs/`;
`db.py` kapselt die SQLite-Datenbank (`bot.db`). Die Münz-Währung wird mit dem
Server-Emoji `:YamiToken:` dargestellt (Fallback 🪙).

> **Server-übergreifend (global):** Coins, XP, Level, Karten, Inventare und Packs
> gehören dem User **über alle Server hinweg** (eine Identität). Pro Server bleiben
> nur Einstellungen: getrackte Spiele, Drop-/Level-up-Channel. Leaderboard & Rang
> sind dadurch ebenfalls serverübergreifend.

## Voraussetzungen

- Python 3.11+
- Ein Discord-Account mit Rechten, einen Bot zu erstellen

## 1. Bot im Discord Developer Portal anlegen

1. Öffne das [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → Namen vergeben → **Create**.
3. Links auf **Bot** → **Add Bot** (falls nötig) bestätigen.
4. Unter **Bot** den Token via **Reset Token** anzeigen lassen und kopieren.
   Diesen Token brauchst du gleich für `DISCORD_TOKEN`. **Niemals öffentlich teilen.**

### Pflicht-Intents: Message Content & Server Members

Im Developer Portal unter **Bot** → **Privileged Gateway Intents** müssen **beide**
aktiviert sein, sonst startet der Bot nicht:

1. **Message Content Intent** — Codes erkennen, Nachrichten-XP, Audit-Log.
2. **Server Members Intent** — Willkommensnachrichten, Audit-Log (Join/Leave,
   Rollen-/Nick-Änderungen) und das Entfernen von Reaction Roles beim Entreagieren.

### Optional: Sammelkarten-Rewards (Presence Intent)

Nur nötig für die **Sammelkarten fürs Spielen** (`/cards`). Dafür muss der Bot
sehen, welches Spiel jemand spielt:

1. Im Developer Portal **Presence Intent** aktivieren (Server Members Intent ist
   ohnehin schon Pflicht, siehe oben).
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
| `/level coins @user <coins>` | Coins vergeben/entziehen | Mods |

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

### Profil (`/profile`, `/setbio`, `/setfavcard`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/profile [user]` | Avatar, Level + XP-Balken, Coins, Rang, Spiel-Statistiken, Titel, Ehen, Bio, Lieblingskarten | alle |
| `/setbio <text>` | Eigene Bio setzen (max. 200 Zeichen, leer = löschen) | alle |
| `/setcolor <hex>` | Profil-Akzentfarbe wählen (`#FF8800`; `reset` = Rollenfarbe) | alle |
| `/setfavcard <karte>` | Lieblingskarte für ein Spiel setzen (eine je Spiel) — das Spiel wird aus der Karte erkannt | alle |

Du kannst **pro Spiel** eine Lieblingskarte festlegen. Im `/profile` werden sie
groß als Bild gezeigt und lassen sich mit den **◀/▶**-Buttons durchblättern.
Auf dem **eigenen** `/profile` gibt es zusätzlich einen ⭐-Button, um pro Spiel
eine Karte per Dropdown auszuwählen (oder zu entfernen).

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
| `/say <text> [channel]` | Lässt den Bot eine Nachricht schreiben (`\n` = Zeilenumbruch, `\n\n` = Leerzeile; kein @everyone; wird geloggt) | Nachrichten verwalten / Admin |

Discord erlaubt Massen-Löschen nur für Nachrichten **jünger als 14 Tage**.

### Reaction Roles (`/reactionrole`)

Mitglieder reagieren mit einem Emoji auf eine Nachricht und erhalten dadurch eine
Rolle (Reaktion entfernen → Rolle weg). Verwaltbar per Command **oder** komfortabel
im Webpanel (Channel/Nachricht/Emoji/Rolle auswählen). Optional lässt sich eine
**Voraussetzungs-Rolle** festlegen (auch die **Server-Booster-Rolle**): Nur Mitglieder
mit dieser Rolle bekommen die Reaction Role — wer sie nicht hat, dessen Reaktion wird
automatisch entfernt.

| Command | Beschreibung | Wer? |
|---|---|---|
| `/reactionrole add <message_id> <emoji> <rolle> [channel] [required_role]` | Emoji an einer Nachricht an eine Rolle binden (Bot hängt die Reaktion an); optional auf eine Voraussetzungs-Rolle beschränken | Rollen verwalten |
| `/reactionrole remove <message_id> <emoji>` | Bindung entfernen | Rollen verwalten |
| `/reactionrole list` | Alle Bindungen des Servers anzeigen | Rollen verwalten |

> Voraussetzung: **Server Members Intent** im Developer Portal aktiviert (für das
> Entfernen der Rolle beim Entreagieren) und die **Bot-Rolle über** den zu
> vergebenden Rollen.

### Willkommensnachrichten

Begrüßt neue Mitglieder automatisch in einem gewählten Channel. Vollständig im
**Webpanel** einstellbar (an/aus, Channel, Text, optionales **Banner-Bild** per
Drag-&-Drop/Upload oder URL, mit Live-Vorschau als Discord-Karte). Platzhalter:

| Platzhalter | Bedeutung |
|---|---|
| `{user}` | Erwähnung (@Name) |
| `{user_name}` | Anzeigename |
| `{server}` | Servername |
| `{count}` | aktuelle Mitgliederzahl |

> Voraussetzung: **Server Members Intent** aktiviert (siehe oben).

### Audit-Log

Protokolliert Server-Ereignisse in die Datenbank und zeigt sie im **Webpanel**
(filterbar nach Kategorie). Optional werden Ereignisse zusätzlich live in einen
gewählten Channel gepostet. Jede Kategorie ist im Webpanel einzeln schaltbar:

| Kategorie | Erfasst |
|---|---|
| **Nachrichten** | gelöschte & bearbeitete Nachrichten (mit Inhalt) |
| **Voice** | Voice betreten / verlassen / wechseln |
| **Mitglieder** | Join, Leave, Ban, Unban |
| **Rollen & Nicknames** | Rollen vergeben/entfernt, Nick-Änderungen, Rollen erstellt/gelöscht |
| **Channels** | Channels erstellt / gelöscht |

Pro Server werden die letzten 2000 Einträge vorgehalten; im Webpanel lässt sich das
Log auch leeren.

### Ticket-System (`/ticket`)

Privater Support pro Mitglied über **private Threads**. Ein **Panel** (Embed mit
Auswahlmenü) wird in einen Channel gepostet; jede Option ist ein konfigurierbares
**Thema** (z.B. Support, Bewerbung, Report). Wählt jemand ein Thema, öffnet der Bot
einen privaten Thread unter dem Panel-Channel (nur Ersteller + Team), pingt die
Support-Rolle und legt **Übernehmen-/Schließen**-Buttons in den Thread. Beim Schließen
wird ein **Web-Transcript** erzeugt (eigene, hübsch gerenderte Seite unter
`/t/<token>` im Discord-Stil mit Avataren, Anhängen & Markdown) und als Link ins
Log-Channel-Embed gepostet; der Thread wird archiviert & gesperrt. Pro Mitglied sind
bis zu 3 offene Tickets gleichzeitig erlaubt.

**Schließen** darf nur, wer das Ticket **übernommen** hat (`claim`), der **Ersteller**
selbst, oder ein **Admin** (Server verwalten) — andere Mods nicht. Ein noch nicht
übernommenes Ticket kann nur ein Admin (oder der Ersteller) schließen; Mods müssen erst
**Übernehmen** klicken. Im **Webpanel** sind unter *Tickets* **alle Tickets** (offen &
geschlossen) sowie alle **Transcripts** einsehbar.

Einrichtbar per Command **oder** komplett im **Webpanel** (Panel posten, Support-Rolle,
Log-Channel, Panel-Titel/-Text, Themen verwalten):

| Command | Beschreibung |
|---|---|
| `/ticket panel [#channel]` | Panel posten/erneuern und System aktivieren (Mods) |
| `/ticket disable` | System deaktivieren und Panel entfernen (Mods) |
| `/ticket setrole @rolle` | Support-Rolle festlegen (wird bei neuen Tickets gepingt) |
| `/ticket setlog [#channel]` | Channel für Transcripts (weglassen = aus) |
| `/ticket config` | Aktuelle Konfiguration anzeigen |
| `/ticket category add <name> [emoji] [text]` | Thema (Panel-Option) anlegen |
| `/ticket category remove <id>` · `list` | Themen entfernen / anzeigen |
| `/ticket claim` | Aktuelles Ticket übernehmen (Support) |
| `/ticket add @user` | Mitglied zum aktuellen Ticket hinzufügen (Support) |
| `/ticket close` | Ticket schließen (Bearbeiter/Claimer, Ersteller oder Admin) |

> Voraussetzung: Der Bot braucht im Panel-Channel die Rechte **Private Threads
> erstellen** und **Threads verwalten**. Damit das Support-Team alle Tickets sieht,
> sollte die Support-Rolle **Threads verwalten** haben (sonst nur per `/ticket add`).
> Für die **Transcript-Links** muss `WEB_BASE_URL` gesetzt sein (gleiche Variable wie
> fürs Webpanel) — sonst wird das Transcript zwar gespeichert, aber ohne klickbaren Link.

### Fun & Sonstiges

| Command | Beschreibung |
|---|---|
| `/8ball <frage>` | Antwort der magischen Miesmuschel |
| `/insult [@user]` | Zufällige, harmlose deutsche Beleidigung |
| `/whoisguilty <verdächtige>` | Bot ermittelt zufällig den „Schuldigen" aus den gepingten Personen |
| `/existential [stil]` | Cursed Weisheiten / Fake-deep Quotes / philosophischer Unsinn |
| `/summondemon` | Beschwört Yami — zufällig gnädig (`:YamiLuv:`) oder erzürnt (Cooldown) |

### Spiel-Sammelkarten (`/gamecards`, `/gamecard`, `/trade`, `/discard`)

| Command | Beschreibung | Wer? |
|---|---|---|
| `/gamecards [user]` | Zeigt die erspielten Sammelkarten | alle |
| `/gamecard <karte>` | Zeigt eine einzelne Karte (Bild + Seltenheit) | alle |
| `/trade @user [karte] [tokens]` | Karten tauschen oder mit Coins kaufen/draufzahlen (beidseitige Bestätigung) | alle |
| `/discard <karte> [anzahl]` | Karten aus der eigenen Sammlung entfernen (mit Rückfrage) | alle |
| `/rewardserver` | Wählen, auf welchem Server die Karten-Drop-Meldungen ankommen (wenn man auf mehreren Servern dasselbe Spiel spielt) | alle |
| `/fuse cards <spiel> <seltenheit>` | **5 Karten einer Seltenheit → 1 zufällige der nächsten** (Common→…→Legendary) | alle |
| `/fuse yami <seltenheit>` | Yami-Karten fusionieren (5 → 1 höher) | alle |
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
**Erfordert das Presence Intent** (siehe unten). Beim Karten-Drop wird nur der
**Name** angezeigt (kein Ping).

**Server-übergreifend:** Inventar und das Tageslimit sind **global pro User** —
wer auf mehreren Servern ist, sammelt ein Spiel nur **einmal** (nicht doppelt).
Pro Server bleibt nur, *ob* ein Spiel getrackt wird und wohin gedroppt wird.

### Booster & Yami-Karten (`/booster`, `/yamicard`)

Zweites Kartensystem mit eigenem Pool. **Yami-Karten** kauft man über Booster-Packs;
zusätzlich gibt es **Spiel-Booster**, die aus dem erspielten Karten-Pool eines
Spiels ziehen (teuer — als Alternative bei ausgeschalteter Aktivität):

| Command | Beschreibung | Wer? |
|---|---|---|
| `/booster buy <typ> [anzahl]` | Yami-Booster-Packs mit Coins kaufen | alle |
| `/booster open <typ> [anzahl]` | Yami-Pack(s) öffnen — Karten **einzeln aufgedeckt** (seltenste zuletzt); bei mehreren zusätzlich „⏭ Übersicht"-Button | alle |
| `/booster buygame <spiel> [anzahl]` | Spiel-Booster kaufen (**200.000 Coins**, 5 Karten des Spiels) | alle |
| `/booster opengame <spiel> [anzahl]` | Spiel-Booster öffnen → Karten in `/gamecards`; **0,2 % Godpack-Chance** ✨ (mehrere auf einmal möglich) | alle |
| `/booster packs` | Ungeöffnete Packs anzeigen | alle |
| `/booster collection [user]` | Yami-Karten-Sammlung | alle |
| `/booster card <karte>` | Eine Yami-Karte ansehen | alle |
| `/yamicard add <name> <seltenheit> <bild-url>` | Yami-Karte anlegen (Bild-URL Pflicht) | Server verwalten / Admin |
| `/yamicard remove <karte>` / `list` | Karte entfernen / alle anzeigen | Server verwalten / Admin |

**Aufdecken:** Beim Öffnen werden die Karten **nacheinander per „Weiter“-Button**
aufgedeckt — die **seltenste zuletzt**, für mehr Spannung.

**Godpack** (nur Spiel-Booster): Mit **0,2 %** Chance enthält ein Spiel-Booster
stattdessen **eine einzige** Karte, ausschließlich **Legendary** oder **Mythic**
(Mythic nur in 3 % der Godpacks). Hat das Spiel keine Legendary/Mythic-Karten,
öffnet sich ein normales Pack.

Pack-Tiers (in `cogs/booster.py` anpassbar): **Standard** (2.000 Coins, 5 Karten) und
**Premium** (5.000 Coins, 5 Karten, bessere Chancen auf seltene Karten). Packs werden
mit Coins gekauft, sammeln sich an und werden mit `/booster open` geöffnet; die Karten
landen in der separaten Yami-Karten-Sammlung. Auch im `/shop` gelistet. **Spiel-Booster**
(`/booster buygame`, 200.000 Coins) ziehen dagegen aus dem erspielten Pool eines Spiels
und landen in der `/gamecards`-Sammlung.

### Webpanel (optionales Admin-Web-UI)

Über `WEB_ENABLED=1` startet im Bot-Prozess ein aiohttp-Server mit Discord-OAuth-Login.
Zugriff hat, wer auf einem Server (auf dem der Bot ist) **„Server verwalten"** hat.
Seiten: Übersicht, **Sammelkarten** (Bild-Upload), **Yami-Karten**, **Economy**
(Leaderboard + Coins anpassen), **Inventare** (ansehen + Karten entfernen),
**Spiele & Channel**. Bei mehreren Servern gibt es oben einen **Server-Umschalter**.

Konfiguration per Env (siehe `.env.example`): `WEB_BASE_URL`, `OAUTH_CLIENT_ID`,
`OAUTH_CLIENT_SECRET`, optional `WEB_HOST`/`WEB_PORT`. Mit **`WEB_OWNER_IDS`**
(komma-getrennte Discord-User-IDs) lässt sich das **Hoch-/Runterladen von Karten**
auf bestimmte Personen beschränken — leer = alle Admins (wie bisher), Ansehen bleibt
für alle Admins möglich.

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
