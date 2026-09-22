# Oaken Tower Hash-Code Discord Bot — Spec

## Ziel
Ein Discord-Bot, der in einem freigeschalteten Channel automatisch den **alten Oaken-Tower-Code eines Users löscht**, sobald derselbe User einen **neuen Code** postet. So bleibt der Channel sauber und es ist auf einen Blick erkennbar, welcher Code aktuell gültig ist.

## Kontext
[Oaken Tower](https://store.steampowered.com/app/3400960/Oaken_Tower/) ist ein synergie-lastiger PvP-Auto-Battler von Bocary Studios, in dem der eigene Item-Tower gegen andere Spieler kämpft. Für 1v1-Matches teilen Spieler lange, Base64-artige Hash-Codes im Discord-Channel, um sich direkt zu matchen. Da pro Match ein neuer Code generiert wird, sammeln sich veraltete Codes an und der Channel wird unübersichtlich.

## Code-Format

Oaken-Tower-Codes sind lange, Base64-ähnliche Strings (typischerweise **500–1500 Zeichen**) bestehend aus:
- Buchstaben (`a–z`, `A–Z`)
- Ziffern (`0–9`)
- Sonderzeichen: `+`, `/`, `=`

### Beispiel
```
1Soa2Tw99Fve3MuyH9b5gr/0Oq+CzPkSPKVETMdP9/l5r8/3qMuYPuEiMJPuC+8KI+BWuPLupO9MUC6yXiR/Nc7CIze1j+nqOJB5Jmf4457LsMx22gwxl3ccmW+RgapwpknvWgavtKnlBlDU1HanXeiyvvGnSO4ftpE355zZt6Mu6RXjgSVCyWURug6A3DledKuTIxNrhdULEZw13PbN823TxN78a1Knj3AmKH9Omc1rlEJUf+XxwcbsRx1TamVvUGFyW3npUAbslMkl3Nm2L8GhQuuDgkX9QlohzLkSI0UT0NAzGdaZwwcipxfFQ1CtBjYdzOJbpE2XmaeZsPcs2hdOoQsdvODDShImuTpBlH/w0IRL8G2Nl0MD8BYk0RlVPm78lNNgt/wplSGaUbDiCfGFMOw6RiodI9cuINsPtQSY8K1SS2z7NF1iJXsikEP0rUVLfzVcE6v7jej3+7yU7B9MYQk2my6NjcPZdZtV+TsUTTyHk3kLoVEEX9Eao5BJGgzGUUGl5BEtIU5DGwKU0NkK0Ha4bEJvUWr2AAoDLIiskfFXStibF1E4y0dEXR2thQydRup3ndYznzxhhEKETYxYb3x/RQkJ2bt99eXWnYncSgb5h2ueV6IEPjNhnF8fh+TLQEzGP1UVNzJe
```

### Erkennungs-Pattern
Ein **zusammenhängender Block** aus Base64-Zeichen mit mindestens **200 Zeichen**, um normale Nachrichten und kurze Strings (Token-Reste, IDs etc.) sicher auszuschließen:

```regex
[A-Za-z0-9+/=]{200,}
```

Wichtig: Der Code wird typischerweise als **gesamter Inhalt** der Message gepostet (evtl. mit Whitespace drumherum). Das Pattern muss nicht den ganzen String matchen — `re.search` reicht.

## Funktionsanforderungen

### Auto-Delete-Logik
1. Bot beobachtet alle Messages in aktivierten Channels.
2. Erfüllt eine Message das Erkennungs-Pattern → sie gilt als **Code-Message**.
3. Hat **derselbe Author** in **diesem Channel** bereits eine Code-Message gepostet (deren ID gespeichert ist), wird die alte gelöscht.
4. Die neue Message-ID wird für diesen User/Channel gespeichert.
5. Codes **anderer User** bleiben unangetastet — beide Spieler eines Matches sollen ihren Code parallel teilen können.

### Slash Commands
| Command | Beschreibung |
|---|---|
| `/aktivieren` | Aktiviert Auto-Delete im aktuellen Channel |
| `/deaktivieren` | Deaktiviert Auto-Delete im aktuellen Channel |
| `/status` | Zeigt, ob Auto-Delete in diesem Channel aktiv ist |
| `/reset` | Vergisst gespeicherte Code-Message-IDs in diesem Channel (nichts wird gelöscht, nur das Tracking) |

Alle Antworten als `ephemeral=True` (nur für den ausführenden User sichtbar), damit der Channel sauber bleibt.

### Berechtigungen
- `/aktivieren`, `/deaktivieren`, `/reset` nur für Mitglieder mit **Manage Channels** oder **Administrator**. Mit `@app_commands.default_permissions(manage_channels=True)` umsetzen.
- `/status` für alle.

### Persistenz
Konfiguration überlebt Bot-Neustarts via `config.json`:

```json
{
  "<channel_id>": {
    "enabled": true,
    "last_codes": {
      "<user_id>": <message_id>
    }
  }
}
```

Bei jeder Änderung sofort speichern (synchroner Disk-Write reicht — kein Performance-Problem bei der erwarteten Last).

## Technische Vorgaben
- **Sprache:** Python 3.11+
- **Library:** `discord.py` (aktuelle stabile Version, ≥ 2.4)
- **Intents:** `default()` + `message_content = True`
- **Token-Quelle:** Umgebungsvariable `DISCORD_TOKEN`
- **Slash Commands:** beim `on_ready` via `bot.tree.sync()` synchronisieren
- **Plattform:** Linux (CachyOS, KDE Plasma 6, fish-Shell)

## Edge Cases & Fehlerbehandlung
- Alte Message wurde von Hand schon gelöscht → `discord.NotFound` abfangen, weiter machen
- Bot hat keine `Manage Messages`-Permission → `discord.Forbidden` abfangen, weiter machen
- Message ist eine DM (`message.guild is None`) → ignorieren
- Bot-Messages (`message.author.bot`) → ignorieren
- Embeds/Anhänge ohne Text → ignorieren (Pattern matcht nicht, fertig)
- Ungültige IDs in `config.json` beim Laden → defensiv parsen, fehlerhafte Einträge verwerfen

## Deliverables
1. **`bot.py`** — Haupt-Bot-Datei mit allen Commands und Event-Handlern
2. **`requirements.txt`** — Python-Dependencies (`discord.py>=2.4`)
3. **`README.md`** — Setup-Anleitung:
   - Bot im Discord Developer Portal anlegen
   - `Message Content Intent` aktivieren
   - Einladungs-URL mit Permissions `Send Messages`, `Manage Messages`, `Use Application Commands`
   - `pip install -r requirements.txt`
   - `DISCORD_TOKEN` als ENV setzen (oder `.env` mit `python-dotenv`)
   - `python bot.py`
   - In gewünschtem Channel `/aktivieren` ausführen
4. **`.env.example`** — Vorlage mit `DISCORD_TOKEN=` (leer)
5. **`.gitignore`** — schließt `config.json`, `.env`, `__pycache__/` aus

## Coding-Style
- Type Hints überall
- Docstrings für Module und nicht-triviale Funktionen
- Konstanten oben im File (`DEFAULT_PATTERN`, `CONFIG_FILE`)
- Logging via `logging`-Modul auf INFO-Level (nicht `print`), Bot-Start und Lösch-Aktionen mitloggen
- Keine externen Dependencies außer `discord.py` (und optional `python-dotenv`)

## Out of Scope (bewusst weglassen)
- Kein konfigurierbares Pattern (Bot ist nur für Oaken Tower → Pattern hardcoden)
- Keine Datenbank (JSON reicht)
- Kein Web-Dashboard
- Keine Multi-Server-Statistiken
- Kein Re-Posten / Edit der Codes
