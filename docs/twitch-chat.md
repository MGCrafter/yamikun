# Yamikun im Twitch-Chat

`https://yamikun.eu/twitch` ist eine eigene Seite mit Twitch-Anmeldung. Sie ist
unabhängig von den Discord-Servereinstellungen unter `/g/:gid/twitch`.
Die bisherigen Live-Benachrichtigungen laufen unverändert weiter.

## Einmalige Einrichtung in CapRover

1. Ein separates Twitch-Konto für Yami anlegen bzw. das vorhandene Botkonto nutzen.
2. In der [Twitch Developer Console](https://dev.twitch.tv/console/apps) die
   bestehende **vertrauliche / confidential** App verwenden. Als OAuth-Redirect
   zusätzlich exakt `https://yamikun.eu/twitch/callback` eintragen.
   Bei einer anderen Domain gilt `<WEB_BASE_URL>/twitch/callback`.
3. Das neue Image mit den aktualisierten `requirements.txt` deployen.
   Der Docker-Build erstellt auch die neue React-Seite. Das persistente `/data`
   und die bestehende `bot.db` bleiben erhalten; Tabellen werden ergänzt.
4. Folgende Umgebungsvariablen setzen:

   | Variable | Wert |
   | --- | --- |
   | `WEB_ENABLED` | `1` |
   | `WEB_BASE_URL` | `https://yamikun.eu` |
   | `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | Bereits vorhandene Twitch-App |
   | `TWITCH_CHAT_ENABLED` | `1` |
   | `TWITCH_BOT_USER_ID` | Numerische Twitch-ID des Botkontos |
   | `TWITCH_EVENTSUB_SECRET` | Zufälliges Geheimnis, 32–100 ASCII-Zeichen |
   | `TWITCH_TOKEN_KEY` | Dauerhafter Fernet-Schlüssel |

   Das vorhandene Discord-Webpanel benötigt weiterhin seine
   `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET`.

   Geheimnisse einmal erzeugen und sicher in CapRover sowie im Backup ablegen:

   ```bash
   python -c 'import secrets; print(secrets.token_hex(32))'
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

   `TWITCH_TOKEN_KEY` bei normalen Deployments **nicht neu generieren**: damit
   sind die gespeicherten Twitch-Zugangsdaten verschlüsselt. Bei Schlüsselverlust
   müssen Botkonto und Streamer ihre Twitch-Freigaben erneuern.
   Die Bot-ID lässt sich mit den App-Zugangsdaten aus der Umgebung bestimmen:
   `python scripts/twitch_bot_id.py bot_login_name`.

5. HTTPS in CapRover aktivieren. Twitch muss den Endpunkt
   `POST https://yamikun.eu/twitch/eventsub` über Port 443 erreichen können.
   Kein zusätzlicher Basic-Auth-/Login-Schutz oder Browser-Challenge auf diesem
   Pfad. Der Handler prüft selbst Twitchs Signatur und Zeitstempel.
6. `https://yamikun.eu/twitch?setup=bot` öffnen, **Botkonto verbinden** wählen und
   mit genau dem Konto aus `TWITCH_BOT_USER_ID` anmelden. Andere Konten werden
   abgewiesen. Bot-Scopes: `user:read:chat`, `user:write:chat`, `user:bot`.
   Wer sich mit dem Botkonto zunächst über die normale Twitch-Anmeldung einloggt,
   sieht im Dashboard automatisch den Bereich **Yamis Botkonto** mit dem Button
   **Botkonto verbinden**. Der Bereich wird anhand der bestätigten Twitch-ID
   erkannt. Die normale Anmeldung allein erteilt die Bot-Freigabe noch nicht.
   Den gesamten Vorgang im selben Browser starten und abschließen.
7. Mit dem eigenen Streamer-Konto `/twitch` öffnen, Twitch-Freigabe erteilen und
   **Bot zu meinem Channel hinzufügen** wählen. Die Verbindung wird normalerweise
   innerhalb einer Minute bestätigt. Twitch vergibt dafür `channel:bot` sowie
   die Freigaben zum Löschen von Nachrichten und Vergeben von Timeouts.

Yami liest Chat-Nachrichten über EventSub-Webhooks und antwortet über die Send
Chat Message API unter dem Botkonto. AutoMod nutzt die Freigabe des Broadcasters
und führt Aktionen in dessen Namen aus; eine zusätzliche manuelle Moderatorrolle
für das Botkonto ist dafür nicht erforderlich.

### Chat-Ereignisse kommen an, aber Yami antwortet nicht

`POST /twitch/eventsub` mit Status `204` bestätigt nur den Empfang des Ereignisses.
Die anschließende Chat-Antwort kann Twitch separat ablehnen. Im Dashboard und
in der Logzeile `Twitch-Chat: Zustellung fehlgeschlagen` stehen deshalb der
Fehlercode, Status und gegebenenfalls Twitchs `drop_reason.code`. Beispielsweise
zeigt `status=200, reason=automod_held`, dass Twitch die Anfrage verarbeitet,
die Nachricht aber zur AutoMod-Prüfung zurückgehalten hat.

- `bot_authorization_missing`: Als Botkonto **Botkonto verbinden** bzw.
  **Botkonto-Freigabe erneuern** wählen.
- `channel_authorization_missing`: Die Anmeldung/Freigabe mit dem Streamer-Konto
  erneuern.
- `msg_verified_email` / `msg_requires_verified_phone_number`: Die verlangte
  Verifizierung in den Twitch-Sicherheitseinstellungen des **Botkontos** erledigen.
- `automod_held`: Die Moderationswarteschlange bei Twitch prüfen.
- `msg_banned` / `msg_timedout`: Bann oder Timeout des Botkontos im Zielchannel prüfen.

Ein Verbindungsabgleich löscht solche Fehler nicht. Sie verschwinden nach einer
erfolgreichen Aktion desselben Typs oder beim Pausieren des Bots. Chat-Antworten
und AutoMod-Aktionen werden getrennt überwacht. Tokens, Chat-Texte und rohe
Twitch-Fehlerantworten werden dabei nicht ins Log geschrieben.

Referenz: [Twitch Send Chat Message](https://dev.twitch.tv/docs/api/reference/#send-chat-message).

## Streamer und Zuschauer

- Streamer verwalten ausschließlich ihren eigenen Channel. Social-Commands,
  Gambling und AutoMod sind getrennt schaltbar. AutoMod ist zunächst aus.
- **Bot pausieren / entfernen** stoppt die Verarbeitung sofort und entfernt das
  EventSub-Abo beim nächsten Abgleich. Einstellungen und Guthaben bleiben erhalten.
  Offene Blackjack-Hände werden abgerechnet und unbeantwortete Duelle erstattet.
- **Abmelden** beendet nur die Browser-Sitzung; der Bot bleibt im Channel aktiv.
- Zuschauer brauchen keine Website-Anmeldung für normale Chat-Commands.
- Für eine optionale Discord-Verknüpfung auf `/twitch` zuerst mit Twitch, dann
  zusätzlich mit Discord anmelden. Vor dem Verbinden wird das Discord-Konto
  angezeigt. Dafür muss der Zuschauer den Bot nicht im eigenen Channel aktivieren.
- Nach der Verknüpfung verwenden alle Twitch-Channels das bestehende globale
  Discord-Guthaben. Lokale Twitch-Coins werden weder übertragen noch addiert;
  nach dem Trennen stehen sie wieder zur Verfügung. Ein Discord-Konto kann nur
  mit einem Twitch-Konto verbunden sein.
- Das Daily teilt bei verknüpften Konten den Discord-Cooldown und die
  Streak-Belohnung. Einstellbare Channel-Dailys gelten ausschließlich für lokale
  Twitch-Coins. Überweisungen und Duelle sind nur zwischen demselben Coin-Typ
  möglich. Während offener Twitch-Spiele kann die Verknüpfung nicht geändert werden.
- Freundschaften, Ehen, Friendship-XP und Spielrunden bleiben pro Twitch-Channel.
  Discord-Profile, Achievements und Shop-Effekte werden nicht übernommen.

## Commands

Standard-Präfix ist `!`; erlaubt sind 1–3 Zeichen aus `! ? . $`.

| Command | Funktion |
| --- | --- |
| `!help`, `!commands` | Übersicht aktivierter Module |
| `!coins`, `!balance` | Aktuelles Guthaben und Coin-Typ |
| `!daily` | Daily alle 24 Stunden |
| `!pay @name 50` | Überweisung |
| `!leaderboard`, `!top` | Top 5 im Channel |
| `!hug`, `!pat`, `!kiss`, `!slap`, `!highfive @name` | Social-Aktionen |
| `!friend add / accept / remove / level @name` | Freundschaften mit Zustimmung |
| `!friend list / requests` | Freunde / eingehende Anfragen |
| `!marry @name`, `!marry accept / decline @name` | Heiratsantrag / Antwort |
| `!marriages`, `!divorce @name` | Ehen anzeigen / beenden |
| `!coinflip 50 kopf`, `!cf 50 zahl` | Auszahlung bei Treffer: 2× Einsatz |
| `!slots 50` | Drei Gleiche; Auszahlungen und Grundwahrscheinlichkeiten wie im Discord-Bot |
| `!roulette 50 rot` | Europäisches Rad, 0–36 |
| `!roulette 50 zahl 17` | Einzelzahl, auch `!roulette 50 17` |
| `!blackjack 50`, `!bj 50` | Gegen den Dealer |
| `!hit`, `!stand`, `!double`, `!split` | Blackjack steuern |
| `!blackjackduel @name 50` | Einsatz reservieren und Duell anbieten |
| `!blackjackduel accept / decline @name` | Angebot beantworten; danach `!hit` / `!stand` |

Roulette kennt auch `schwarz`, `gerade`, `ungerade`, `tief`, `hoch`,
`dutzend1`–`dutzend3` und `spalte1`–`spalte3`. 0 verliert Außenwetten.
Blackjack: Dealer bleibt ab 17 stehen, Natural zahlt 3:2 Gewinn (halbe Coins
werden abgerundet), Gleichstand gibt den Einsatz zurück. Bis zu vier Split-Hände;
Split braucht gleiche Ränge. Pro Person und Channel nur eine offene Runde bzw.
Duellanfrage. Nach 120 Sekunden automatisch Stand; Duelle sind offen sichtbare
Hände ohne Split/Double. Der konfigurierbare Höchsteinsatz gilt je Anfangseinsatz,
Split und Double erfordern zusätzliches Guthaben.

Andere Personen müssen zuvor im Chat geschrieben haben, damit ihre stabile
Twitch-ID bekannt ist. Namen allein werden nicht als dauerhafte Identität genutzt.
Alle Beträge sind virtuelle Coins ohne Echtgeldkäufe oder Auszahlung.

Die Blackjack-Anzeige nennt die eigenen Punkte und markiert die verdeckte
Dealer-Karte ausdrücklich. `double` und `split` erscheinen nur, wenn Karten,
Handanzahl und Guthaben die Aktion erlauben. Nach einem Split steht dort etwa
`Hand 2/3`; das Ergebnis zeigt Gewinn, Verlust, Gleichstand oder Überkauft.

## Automatische Chatnachrichten

Unter `/twitch` im eigenen Dashboard **Automatische Nachrichten → Nachricht
hinzufügen** wählen. Bis zu 20 Nachrichten sind pro Channel möglich:

- **Name:** interne Bezeichnung, maximal 60 Zeichen.
- **Nachricht im Chat:** bis zu 500 Zeichen einschließlich Links und Emotes,
  als eine Zeile. Die Vorschau zeigt den Text; Platzhalter werden nicht ersetzt.
- **Intervall:** 1–1.440 Minuten, standardmäßig 15 Minuten.
- **Mindestens Chatnachrichten:** 0–1.000 neue, nicht durch Yamis AutoMod
  gefilterte Nachrichten seit dem letzten Versandversuch, standardmäßig 5.
  Eigene Botnachrichten, doppelte Zustellungen und Shared-Chat-Weiterleitungen
  zählen nicht. `0` deaktiviert diese zusätzliche Bedingung.
- **Nur senden, wenn ich live bin:** standardmäßig aktiviert. Der Livestatus
  wird bei fälligen Nachrichten über [Get Streams](https://dev.twitch.tv/docs/api/reference/#get-streams)
  geprüft und höchstens eine Minute zwischengespeichert. Ohne bestätigten
  Livestatus wird eine solche Nachricht nicht versendet.
- Jede Nachricht kann einzeln pausiert, bearbeitet oder entfernt werden.

Mit **Einstellungen speichern** übernehmen. Intervall und Mindestaktivität
müssen beide erfüllt sein. Nach Anlegen, Bearbeiten oder erneutem Aktivieren
beginnt das Intervall neu. Das Speichern anderer Einstellungen setzt bestehende
Timer nicht zurück. **Bot pausieren / entfernen** stoppt alle Timer und verwirft
wartende Kopien; gespeicherte Nachrichtentexte bleiben erhalten.

Timer und Aktivitätszähler liegen in SQLite und überstehen Neustarts. Der Worker
prüft etwa alle 15 Sekunden; Autonachrichten nutzen die bestehende begrenzte
Versandwarteschlange. Pro Channel wird höchstens eine Autonachricht pro Minute
eingeplant und zwischen erfolgreichen Sendungen liegt ebenfalls mindestens eine
Minute. Verpasste Intervalle werden nicht gesammelt nachgesendet. Bei Ablehnung
oder unklarem Timeout gelten dieselben Regeln wie für Chatantworten; Fehler
erscheinen im Dashboard. Für die nächste Wiederholung gelten erneut das Intervall
und die Mindestaktivität. Es sind keine zusätzlichen Twitch-Freigaben erforderlich.

Die neuen Tabellen werden beim Start automatisch ergänzt; bestehende Channels
beginnen ohne Autonachrichten.

## AutoMod und Betrieb

Eigene Filter ergänzen Twitchs eingebauten AutoMod: Links, Caps (mindestens
12 Buchstaben, davon 80 % groß), Spam (6 Nachrichten oder 3 identische Nachrichten
in 8 Sekunden) und bis zu 100 gesperrte Begriffe. Begriffe werden ohne Beachtung
der Groß-/Kleinschreibung und auch innerhalb längerer Wörter erkannt. Keine
frei eingebbaren regulären Ausdrücke. Broadcaster und Moderatoren sind ausgenommen.
Timeout `0` löscht nur die einzelne Nachricht; sonst gilt die eingestellte Dauer.
Das Dashboard zeigt Erfolg oder Fehler der letzten Aktionen. Moderationsprotokolle
werden 30 Tage aufbewahrt. Der Spam-Zähler liegt im Arbeitsspeicher und beginnt
nach einem Neustart neu.

Webhooks werden schnell bestätigt und dauerhaft zwischengespeichert. Chat-ID,
Spielmutation und Ergebnis werden atomar verarbeitet; doppelte Twitch-Zustellungen
zahlen nicht erneut aus. Offene Spiele überstehen Neustarts. Ergebnisse werden
24 Stunden aufbewahrt, der ursprüngliche Chat-Text wird nach der Verarbeitung
und Zustellung entfernt. Weitergeleitete Shared-Chat-Nachrichten lösen keine
Commands oder Moderation in fremden Channels aus.

Antworten werden konservativ auf etwa 20 Nachrichten pro 30 Sekunden begrenzt,
AutoMod hat einen eigenen Zustellungs-Worker. Temporäre API-Fehler werden begrenzt
wiederholt; bei unklarem Netzwerk-Timeout wird eine Chat-Antwort nicht erneut
gesendet. Eine gebuchte Spielauszahlung wird dadurch nicht erneut ausgeführt.
Über zwei Minuten alte Nachrichten/Aktionen werden nicht nachträglich ausgeführt.
Bereits verbuchte Spiele bleiben auch bei einer fehlgeschlagenen Chat-Antwort
verbucht; `!coins` zeigt den aktuellen Stand. Bei sehr großen Channels kann
deshalb ein höherer Command-Cooldown sinnvoll sein.

Access-/Refresh-Tokens liegen verschlüsselt in SQLite und werden nicht an den
Browser ausgeliefert. Twitch-Tokens werden beim Start und mindestens stündlich
validiert; Refresh-Tokens werden bei Bedarf erneuert. Bei widerrufener Freigabe
wird der Channel deaktiviert und die Web-Sitzung ungültig. Sessions und OAuth-State
werden nur als Hash gespeichert; mutierende APIs benötigen ein CSRF-Token.

Tests: `bash scripts/check.sh`. Der automatisierte Testlauf verwendet temporäre
Datenbanken und simulierte Twitch-Antworten. Für den Live-Test nach Einrichtung:
Anmeldung → Bot hinzufügen → `!daily`, `!coins`, `!hug`, Gambling → AutoMod mit
einem gewöhnlichen Zuschauer testen → pausieren. Der reale OAuth-/Webhook-Rundlauf
braucht die Produktions-Credentials und eine öffentlich erreichbare HTTPS-URL.

Technische Referenzen: [Chat-Autorisierung](https://dev.twitch.tv/docs/chat/authenticating/),
[EventSub-Webhooks](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/),
[Token-Validierung](https://dev.twitch.tv/docs/authentication/validate-tokens/),
[Chat- und Moderations-API](https://dev.twitch.tv/docs/api/reference/).
