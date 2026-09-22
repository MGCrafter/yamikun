# Yumikun — Vollständiges Command-Inventar

> Stand: 2026-06-04 · Automatisch analysiert aus allen geladenen Cogs (`bot.py` COGS-Tuple).
> Cogs ohne Slash-Commands (welcome, boostnotify, autoroles, audit, uiembeds, webpanel)
> sind als Listener/Web-Backend vermerkt, aber nicht tabellarisch aufgeführt.

---

## Inhaltsverzeichnis
1. [Kategorie-Übersichtstabelle](#kategorie-übersichtstabelle)
2. [Cleanup-Vorschläge](#cleanup-vorschläge)
3. [Empfohlene Konventionen](#empfohlene-konventionen)

---

## Kategorie-Übersichtstabelle

### Gambling (Fun/Economy)
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/coinflip` | Setze Coins auf Head oder Tail. Triffst du, verdoppelt sich der Einsatz! | `gambling.py` | guild_only | OK | Behalten |
| `/blackjack` | Spiele Blackjack gegen den Dealer. | `blackjack.py` | guild_only | OK | Behalten |
| `/blackjackduel` | 1v1-Blackjack: Beide setzen denselben Betrag, wer die höhere Hand hat, gewinnt. | `blackjack.py` | guild_only | OK | Umbenannt von `/blackjackvs`; Beschreibung verbessert |
| `/slots` | Drehe die Slot-Machine. Drei Gleiche gewinnen! | `slots.py` | guild_only | OK | Behalten |
| `/roulette` | Setze auf Rot/Schwarz, Zahlen, Dutzende … und dreh das Rad. | `roulette.py` | guild_only | OK | Behalten |

### Economy
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/daily` | Hole deine tägliche Coin-Belohnung ab. | `economy.py` | guild_only | OK | Behalten |
| `/pay` | Überweise einem anderen Mitglied Coins. | `economy.py` | guild_only | OK | Behalten |
| `/shop` | Zeigt kaufbare Boosts und Booster-Packs im Überblick. | `shop.py` | guild_only | OK | Beschreibung verbessert |
| `/buy` | Kaufe ein Item aus dem Shop. | `shop.py` | guild_only | OK | Behalten |

### Leveling
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/rank` | Zeigt Level, XP-Fortschritt und Coins. | `leveling.py` | guild_only | OK | Behalten |
| `/leaderboard` | Zeigt die Top 10 Mitglieder nach Gesamt-XP. | `leveling.py` | guild_only | OK | Beschreibung verbessert |
| `/level setchannel` | Setzt den Channel für Level-Up-Meldungen. | `leveling.py` | manage_channels (Gruppe) | OK | Behalten |
| `/level message` | Eigener Level-Up-Text (leer = Standard-Embed). | `leveling.py` | manage_channels (Gruppe) | OK | Behalten |
| `/level ping` | Soll der User beim Level-Up gepingt werden? | `leveling.py` | manage_channels (Gruppe) | OK | Behalten |
| `/level coins` | Vergibt oder entzieht Coins eines Users. | `leveling.py` | manage_channels (Gruppe) | OK | Umbenannt von `/level give` |

### Profil
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/profile` | Zeigt das Profil eines Users. | `profile.py` | guild_only | OK | Behalten |
| `/setbio` | Setzt deine Profil-Bio. | `profile.py` | guild_only | OK | Behalten |
| `/setcolor` | Setzt deine Profil-Akzentfarbe (Hex, z.B. #FF8800). | `profile.py` | guild_only | OK | Behalten |
| `/setfavcard` | Setzt deine Lieblingskarte für ein Spiel (Spiel wird aus der Karte erkannt). | `profile.py` | guild_only | OK | Behalten |

### Social & Interactions
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/hug` | Umarme jemanden. | `interactions.py` | guild_only | OK | Behalten |
| `/pat` | Tätschle jemandem den Kopf. | `interactions.py` | guild_only | Improve-description | `user`-Param-Beschreibung „Wen?" statt aussagekräftiger Text; für User in Ordnung |
| `/kiss` | Küsse jemanden. | `interactions.py` | guild_only | OK | Behalten |
| `/slap` | Verpasse jemandem eine (spaßige) Ohrfeige. | `interactions.py` | guild_only | OK | Behalten |
| `/highfive` | Gib jemandem ein High-Five. | `interactions.py` | guild_only | OK | Behalten |
| `/friend add` | Schicke jemandem eine Freundschaftsanfrage. | `social.py` | guild_only | OK | Behalten |
| `/friend accept` | Nimm eine Freundschaftsanfrage an. | `social.py` | guild_only | OK | Behalten |
| `/friend remove` | Entferne eine Freundschaft oder Anfrage. | `social.py` | guild_only | OK | Behalten |
| `/friend requests` | Zeigt offene eingehende Freundschaftsanfragen. | `social.py` | guild_only | OK | Behalten |
| `/friend list` | Zeigt deine Freunde und Friendship-Level. | `social.py` | guild_only | OK | Behalten |
| `/friend level` | Zeigt euer Friendship-Level mit jemandem. | `social.py` | guild_only | OK | Behalten |
| `/marry` | Mache jemandem einen Heiratsantrag. | `marry.py` | guild_only | OK | Behalten |
| `/divorce` | Lass dich von jemandem scheiden. | `marry.py` | guild_only | OK | Behalten |
| `/marriages` | Zeigt, mit wem jemand verheiratet ist. | `marry.py` | guild_only | OK | Behalten |

### LFG — Gruppensuche
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/lfg start` | Erstelle eine Gruppensuche. | `lfg.py` | guild_only | OK | Behalten |
| `/lfg role` | Melde dich für LFG-Pings an oder ab. | `lfg.py` | guild_only | OK | Behalten |
| `/lfg setrole` | Setzt die Rolle, die bei /lfg start gepingt wird. | `lfg.py` | manage_roles (default_permissions) | OK | Redundanter has_permissions-Dekorator entfernt |

### Titel
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/title list` | Zeigt alle Titel und ob du sie freigeschaltet hast. | `titles.py` | guild_only | OK | Behalten |
| `/title set` | Wähle einen freigeschalteten Titel. | `titles.py` | guild_only | OK | Behalten |
| `/title clear` | Entfernt deinen aktiven Titel. | `titles.py` | guild_only | OK | Behalten |

### Sammelkarten — Spiel-Rewards
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/gamecards` | Zeigt deine erspielten Sammelkarten. | `gamecards.py` | guild_only | OK | Behalten |
| `/gamecard` | Zeigt eine einzelne erspielte Karte. | `gamecards.py` | guild_only | OK | Behalten |
| `/discard` | Entfernt Karten aus deiner Sammlung. | `gamecards.py` | guild_only | OK | Behalten |
| `/trade` | Tausche oder kaufe eine Karte — optional mit Tokens drauf. | `gamecards.py` | guild_only | OK | Behalten |
| `/rewardserver` | Wähle, auf welchem Server du deine Karten-Drop-Meldungen bekommst. | `gamecards.py` | keiner (global nutzbar) | OK | Behalten |
| `/gamereward addgame` | Fügt ein Spiel hinzu oder ändert dessen Intervall/Tageslimit. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward removegame` | Entfernt ein Belohnungs-Spiel. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward listgames` | Zeigt alle Belohnungs-Spiele. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward setchannel` | Channel für Karten-Drop-Meldungen (ohne Angabe: DMs). | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward addcard` | Legt eine Karte für ein Spiel an. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward removecard` | Entfernt eine eigene Karte. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward givecard` | Vergibt eine Karte direkt an ein Mitglied (z. B. für Giveaways). | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |
| `/gamereward listcards` | Zeigt die Karten eines Spiels. | `gamecards.py` | manage_guild (Gruppe) | OK | Behalten |

### Booster & Yami-Karten
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/booster buy` | Kaufe Booster-Packs mit Coins. | `booster.py` | guild_only | OK | Behalten |
| `/booster open` | Öffne ein oder mehrere Booster-Packs. | `booster.py` | guild_only | OK | Behalten |
| `/booster buygame` | Kaufe einen Spiel-Booster mit Karten eines bestimmten Spiels (200.000 Coins). | `booster.py` | guild_only | OK | Beschreibung verbessert |
| `/booster opengame` | Öffne ein oder mehrere Spiel-Booster — Karten landen in deiner Sammlung. | `booster.py` | guild_only | OK | Behalten |
| `/booster packs` | Zeigt deine ungeöffneten Packs. | `booster.py` | guild_only | OK | Behalten |
| `/booster collection` | Zeigt deine Yami-Karten-Sammlung. | `booster.py` | guild_only | OK | Behalten |
| `/booster card` | Zeigt eine Yami-Karte. | `booster.py` | guild_only | OK | Behalten |
| `/yamicard add` | Legt eine Yami-Karte an. | `booster.py` | manage_guild (Gruppe) | OK | Behalten |
| `/yamicard remove` | Entfernt eine Yami-Karte. | `booster.py` | manage_guild (Gruppe) | OK | Behalten |
| `/yamicard list` | Zeigt alle Yami-Karten. | `booster.py` | manage_guild (Gruppe) | OK | Behalten |

### Karten-Fusion
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/fuse cards` | Erspielte Sammelkarten eines Spiels fusionieren. | `fusion.py` | guild_only | OK | Behalten |
| `/fuse yami` | Yami-Karten fusionieren. | `fusion.py` | guild_only | OK | Behalten |

### Moderation
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/purge` | Löscht die letzten Nachrichten im Channel (optional nur von einem User). | `moderation.py` | manage_messages (default_permissions + has_permissions) | OK | Behalten; Doppel-Check hier sinnvoll für sichere Mod-Aktionen |
| `/say` | Lässt den Bot eine Nachricht schreiben. | `moderation.py` | manage_messages (default_permissions + has_permissions) | OK | Behalten |

### Moderation/Admin — Reaction Roles
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/reactionrole add` | Bindet ein Emoji an einer Nachricht an eine Rolle. | `reactionroles.py` | manage_roles (Gruppe) | OK | Behalten |
| `/reactionrole remove` | Entfernt eine Reaction-Role-Bindung. | `reactionroles.py` | manage_roles (Gruppe) | OK | Behalten |
| `/reactionrole list` | Zeigt alle Reaction-Role-Bindungen dieses Servers. | `reactionroles.py` | manage_roles (Gruppe) | OK | Behalten |

### Ticket-System
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/ticket panel` | Postet (oder erneuert) das Ticket-Panel in einem Channel. | `tickets.py` | manage_guild (manuelle Check-Funktion) | Inconsistent-errors | Zu `default_permissions(manage_guild=True)` migrieren |
| `/ticket disable` | Deaktiviert das Ticket-System (Panel bleibt entfernt). | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket setrole` | Legt die Support-Rolle fest (wird bei neuen Tickets gepingt). | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket setlog` | Channel für Ticket-Transcripts festlegen (leer = aus). | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket config` | Zeigt die aktuelle Ticket-Konfiguration. | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket close` | Schließt das aktuelle Ticket. | `tickets.py` | Opener / Claimer / manage_guild (intern) | OK | Behalten |
| `/ticket claim` | Übernimmt das aktuelle Ticket (Support). | `tickets.py` | Support-Rolle oder manage_guild (intern) | OK | Behalten |
| `/ticket add` | Fügt jemanden zum aktuellen Ticket hinzu (Support). | `tickets.py` | Support-Rolle oder manage_guild (intern) | OK | Behalten |
| `/ticket category add` | Legt ein Ticket-Thema (Panel-Option) an. | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket category remove` | Entfernt ein Ticket-Thema. | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |
| `/ticket category list` | Zeigt alle Ticket-Themen. | `tickets.py` | manage_guild (manuell) | Inconsistent-errors | Wie oben |

### Oaken-Tower Auto-Delete
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/oaken on` | Aktiviert das automatische Löschen alter Codes im aktuellen Channel. | `oaken.py` | manage_guild (Gruppe) | OK | Permission auf Gruppe gesetzt |
| `/oaken off` | Deaktiviert Auto-Delete im aktuellen Channel. | `oaken.py` | manage_guild (Gruppe) | OK | Permission auf Gruppe gesetzt |
| `/oaken newgame` | Startet ein neues Spiel mit Rundenzählung in diesem Channel. | `oaken.py` | manage_guild (Gruppe) | OK | Permission auf Gruppe gesetzt |
| `/oaken endgame` | Beendet das laufende Spiel (Rundenzählung stoppt). | `oaken.py` | manage_guild (Gruppe) | OK | Permission auf Gruppe gesetzt |
| `/oaken status` | Zeigt Auto-Delete- und Spielstatus dieses Channels. | `oaken.py` | manage_guild (Gruppe) | OK | Behalten |
| `/oaken reset` | Vergisst gespeicherte Code-Message-IDs (löscht nichts, nur Tracking). | `oaken.py` | manage_guild (Gruppe) | OK | Redundanter has_permissions-Dekorator entfernt |

### Announcer
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/announce channel` | Setzt den Announce-Channel. | `announcer.py` | manage_channels (Gruppe) | OK | Behalten |
| `/announce add` | Fügt eine Quelle hinzu (YouTube-Kanal oder RSS-Feed). | `announcer.py` | manage_channels (Gruppe) | OK | Behalten |
| `/announce list` | Zeigt alle überwachten Quellen. | `announcer.py` | manage_channels (Gruppe) | OK | Behalten |
| `/announce remove` | Entfernt eine Quelle anhand ihrer ID. | `announcer.py` | manage_channels (Gruppe) | OK | Behalten |
| `/announce post` | Postet einen Link manuell in den Announce-Channel. | `announcer.py` | manage_channels (Gruppe) | OK | Behalten |

### Fun
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/8ball` | Stelle der magischen Miesmuschel eine Frage. | `fun.py` | keine | OK | Behalten |
| `/insult` | Eine zufällige, harmlose Beleidigung. | `fun.py` | keine | OK | Behalten |
| `/whoisguilty` | Der Bot ermittelt den Schuldigen. | `fun.py` | keine | OK | Behalten |
| `/existential` | Cursed Weisheiten, Fake-deep Quotes & philosophischer Unsinn. | `fun.py` | keine | OK | Behalten |
| `/summondemon` | Beschwöre Yami… auf eigene Gefahr. | `fun.py` | keine (Cooldown 30 s) | OK | Behalten |

### Utility
| Name | Beschreibung | Cog/Datei | Berechtigung | Status | Änderung |
|---|---|---|---|---|---|
| `/help` | Zeigt alle Befehle des Bots. | `help.py` | keine | OK | Behalten |

### Cogs ohne eigene Slash-Commands (reine Listener / Webserver)
| Cog | Funktion |
|---|---|
| `welcome.py` | on_member_join → Willkommensnachricht; konfiguriert nur via Webpanel |
| `boostnotify.py` | on_member_update → Boost-Benachrichtigung; konfiguriert nur via Webpanel |
| `autoroles.py` | on_member_join → Auto-Rollen vergeben; konfiguriert nur via Webpanel |
| `audit.py` | Mehrere Listener → Audit-Log in DB + Channel; konfiguriert nur via Webpanel |
| `webpanel.py` | aiohttp-Webserver mit REST-API und React-SPA; keine Slash-Commands |
| `uiembeds.py` | Hilfsfunktionen für Embeds; keine Slash-Commands |

---

## Cleanup-Vorschläge

### 1. Löschen — Hochvertrauens-Kandidaten

Keine Befehle mit hoher Konfidenz für „Löschen" gefunden. Alle definierten Commands sind aktiv genutzt oder sinnvoll.

> Konservatives Ergebnis: **kein Command sollte entfernt werden**.

---

### 2. Umbenennen

| Aktueller Name | Vorschlag | Datei | Begründung | Konfidenz |
|---|---|---|---|---|
| `/level give` → `/level coins` | ✅ umgesetzt | `leveling.py` | Der Command vergibt *Coins*, nicht Level. Der Name `give` war nicht intuitiv. | **Hoch** |
| `/blackjackvs` → `/blackjackduel` | ✅ umgesetzt | `blackjack.py` | `vs` ist ein englisches Kürzel, das nicht zu den deutschen Command-Namen passt. `duel` ist klar. | **Mittel** |

---

### 3. Permissions vereinheitlichen

#### Problem A: `/oaken on|off|newgame|endgame` — keine Berechtigung gesetzt

Diese vier Subcommands manipulieren den Kanalzustand (Auto-Delete an/aus, Spiel starten/stoppen), sind aber für **alle** Mitglieder zugänglich. Nur `/oaken reset` hat `has_permissions(manage_channels=True)`.

**Empfehlung:** `manage_channels=True` als `default_permissions` auf die **Gruppe** (`oaken`) setzen. `/oaken status` kann für alle sichtbar bleiben, wenn nötig separat ausgenommen.

Datei: `cogs/oaken.py` — Zeile 275–279:
```python
oaken = app_commands.Group(
    name="oaken",
    description="Steuerung des Oaken-Tower Auto-Delete.",
    guild_only=True,
    default_permissions=discord.Permissions(manage_channels=True),  # ← ergänzen
)
```

Den separaten `@app_commands.checks.has_permissions(manage_channels=True)` auf `oaken_reset` danach entfernen (er ist durch die Gruppenregel redundant).

---

#### Problem B: `/lfg setrole` — doppelter Permissions-Check

```python
@lfg.command(…)
@app_commands.default_permissions(manage_roles=True)   # ← Zeile 192
@app_commands.checks.has_permissions(manage_roles=True)  # ← Zeile 193 — redundant
```

`default_permissions` steuert die Discord-Sichtbarkeit und standardmäßige Verfügbarkeit. `checks.has_permissions` erzwingt es zusätzlich zur Laufzeit. Da alle anderen Mod-Gruppen (announce, level, gamereward, yamicard, reactionrole) nur `default_permissions` auf der Gruppe nutzen, ist der `checks`-Dekorator hier inkonsistent und verwirrend.

**Empfehlung:** `@app_commands.checks.has_permissions(manage_roles=True)` auf Zeile 193 entfernen.

---

#### Problem C: `/ticket`-Gruppe — manuelle Prüfung statt `default_permissions`

Die `/ticket`-Admin-Subcommands (panel, disable, setrole, setlog, config, category add/remove/list) prüfen Berechtigungen über eine eigene Hilfsfunktion `_require_manage()`, die `manage_guild` prüft. Das verhindert, dass Discord dem User den Command beim Tippen schon versteckt (UX-Problem). Die Gruppe hat kein `default_permissions`.

**Empfehlung:** Auf die Gruppe `ticket` in `tickets.py` `default_permissions=discord.Permissions(manage_guild=True)` setzen. Subcommands wie `/ticket close`, `/ticket claim`, `/ticket add` haben bewusst eigene interne Logik — die können weiterhin ohne `default_permissions` auf der Group-Ebene verwaltet werden, oder eine separate Untergruppe wird angelegt.

Praktischer Vorschlag — zwei Gruppen:
```python
group = app_commands.Group(name="ticket", …)
admin = app_commands.Group(
    name="admin", parent=group,
    default_permissions=discord.Permissions(manage_guild=True)
)
```
Das ist eine größere Refaktorisierung. Mittelfristig empfohlen, kurzfristig: `default_permissions` auf die Hauptgruppe setzen und akzeptieren, dass `/ticket close|claim|add` ebenfalls versteckt werden (sie funktionieren trotzdem per Berechtigung weiter).

---

### 4. Fehlerbehandlung / Response-Inkonsistenz

#### Problem: Mischung aus direkter Response und defer+followup

Die meisten Befehle antworten direkt mit `interaction.response.send_message(…)`. Einige wenige (moderation, announcer `add`, booster `open/opengame`, reactionroles `add`) nutzen `defer` + `followup`, weil sie > 3 s benötigen. Das ist korrekt und notwendig.

**Kein Handlungsbedarf** — die Pattern sind korrekt auf den Use-Case abgestimmt.

#### Problem: Fehlermeldungen nicht immer ephemeral

Mehrere Gambling-Commands zeigen das Ergebnis öffentlich, Fehlermeldungen ephemeral — das ist die richtige Regel. Es gibt jedoch eine Inkonsistenz:

- `/marry` Fehlermeldung bei selbst/Bot: `ephemeral=True` ✅
- `/divorce` bei nicht verheiratet: `ephemeral=True` ✅
- `/friend add` bei already_friends/already_pending: **kein** `ephemeral=True` — die Meldungen werden öffentlich gepostet.

Datei: `social.py`, `/friend add` Command — die Fehlermeldungen (Code `already_friends`, `already_pending`) sollten `ephemeral=True` bekommen.

#### Problem: `/announce list` und `/gamereward listgames` — kein `ephemeral=True` aber lange Listen

`/announce list` (Zeile 264) antwortet ohne `ephemeral=True`. Bei vielen Feeds entstehen lange, öffentlich sichtbare Listen.

**Empfehlung:** `ephemeral=True` ergänzen (wie bei allen anderen `/announce`-Subcommands auch).

---

### 5. Beschreibungsverbesserungen

| Command | Aktuelle Beschreibung | Verbesserte Beschreibung |
|---|---|---|
| `/leaderboard` | „Top 10 nach XP." | „Zeigt die Top 10 Mitglieder nach Gesamt-XP (Level & Coins)." |
| `/shop` | „Zeigt den Shop." | „Zeigt kaufbare Boosts und Booster-Packs (Glücksbringer, XP-Boost, Karten-Packs)." |
| `/blackjackduel` | „Fordere ein anderes Mitglied zum Blackjack-Duell heraus." | ✅ Umgesetzt: „1v1-Blackjack: Beide setzen denselben Betrag, wer die höhere Hand hat, gewinnt." |
| `/booster buygame` | „Kaufe ein Spiel-Booster mit Karten eines Spiels (teuer!)." | „Kaufe einen Spiel-Booster mit Karten eines bestimmten Spiels (200.000 Coins)." |
| `/rewardserver` | „Wähle, auf welchem Server du deine Karten-Drop-Meldungen bekommst." | Beschreibung ist klar — nur kürzen: „Drop-Benachrichtigungs-Server wählen (bei Mitgliedschaft auf mehreren Servern)." |
| `/oaken on/off` | „Aktiviert Auto-Delete im aktuellen Channel." | „Aktiviert das automatische Löschen alter Codes im aktuellen Channel." |
| `/gamereward setchannel` | „Channel für Karten-Drop-Meldungen (ohne Angabe: DMs)." | „Setzt den Channel für Karten-Drop-Meldungen. Kein Channel = Meldungen per DM." |

---

## Empfohlene Konventionen

### Berechtigungs-Konvention (3 Punkte)

1. **Mod-Gruppen**: Admin-Subcommand-Gruppen erhalten `default_permissions=discord.Permissions(...)` auf der Gruppe selbst — **nicht** auf jedem einzelnen Subcommand und **nicht** zusätzlich via `@app_commands.checks.has_permissions`. Das hält den Code DRY und sorgt für korrekte Discord-UI-Sichtbarkeit. Ausnahmen: Interne Logik-Checks (wie Ticket-Claim für Support-Rolle) bleiben im Command-Body.

2. **Kein doppelter Perms-Check**: `default_permissions` auf der Gruppe + `has_permissions` auf dem Subcommand ist redundant. Nur dann beide verwenden, wenn verschiedene Permissions auf Gruppe vs. Subcommand nötig sind.

3. **guild_only auf Gruppen**: Alle Gruppen sollten `guild_only=True` haben, damit DM-Missbrauch ausgeschlossen ist.

### Fehlerbehandlungs-Konvention (1 Punkt)

4. **Alle Fehlermeldungen sind ephemeral**: Jede Fehlermeldung (Validierungsfehler, fehlende Coins, Permission-Denied) wird mit `ephemeral=True` gesendet, damit der Chat-Verlauf nicht mit Fehlern von Mitgliedern verschmutzt wird. Öffentliche Erfolgs-Antworten (Coinflip-Ergebnis, Hochzeit, Freundschaft) bleiben öffentlich.

---

## Statistik

| Kategorie | Anzahl Commands |
|---|---|
| Gambling | 5 |
| Economy | 4 |
| Leveling | 6 |
| Profil | 4 |
| Social & Interactions | 13 |
| LFG | 3 |
| Titel | 3 |
| Sammelkarten (Spiel-Rewards) | 13 |
| Booster & Yami-Karten | 10 |
| Karten-Fusion | 2 |
| Moderation | 2 |
| Reaction Roles | 3 |
| Ticket-System | 11 |
| Oaken-Tower | 6 |
| Announcer | 5 |
| Fun | 5 |
| Utility (/help) | 1 |
| **Gesamt** | **96** |

> Cogs ohne Slash-Commands (welcome, boostnotify, autoroles, audit, webpanel, uiembeds) sind in dieser Zählung nicht enthalten.
