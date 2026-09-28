# Twitch-Prüfung vom 28.09.2026

Die Twitch-Anbindung hat eine brauchbare, moderne Grundlage. Die größten
Verbesserungen liegen in zuverlässiger Zustellung, verständlicher Diagnose und
konfigurierbaren Commands. Eine vollständige Neuentwicklung ist aus der Prüfung
nicht begründbar.

Geprüft wurden Live-Meldungen, OAuth, EventSub-Eingang, Verarbeitung und Versand,
Timer, Coins/Spiele, AutoMod sowie die Anbindung des Webpanels. Die Aussagen
beziehen sich auf den lokalen Quellcode und automatisierte Tests. Produktionslogs,
laufende CapRover-Konfiguration, tatsächliche Freigaben und ein echter
Twitch-/Discord-Versand waren nicht Bestandteil der Prüfung. Änderungen wurden
lokal vorbereitet, nicht deployt.

**Nachtrag nach der beauftragten Umsetzung:** Eigene Commands mit Vorschau,
Rechten, Aliasnamen und getrennten Cooldowns sind implementiert. Der Versand
verteilt Aufträge fair zwischen Channels, priorisiert Command-Antworten und
speichert Wiederholungszeitpunkte. Ein Überlastschutz greift vor Coin-Buchungen.
Timer ohne Live-Bedingung laufen bei Fehlern der Livestatus-Abfrage weiter.
Das Dashboard zeigt Empfang, Versand, Moderation und Warteschlange getrennt.
Die Datenbankmigration erhält bestehende Daten. Details zur Bedienung stehen in
[Twitch-Chat](twitch-chat.md).

Aktuelle Verifikation: **232 Tests erfolgreich**, TypeScript-Prüfung und
Frontend-Build erfolgreich. Ein isolierter Chromium-Test mit echtem lokalen
Dashboard-Backend prüfte Anlegen, Vorschau, Aliasse, Rechte, Speichern/Neuladen,
Validierung, Pausieren bei unvollständigem Entwurf, Aktivieren, Deaktivieren und
Entfernen. Desktop, 375-Pixel-Ansicht, Querformat und beide Farbmodi wurden geprüft;
keine JavaScript-Fehler. Twitch-Antworten waren dabei simuliert; es wurde keine
Nachricht an echte Twitch- oder Discord-Channels geschickt und nicht deployt.

## So funktioniert es aktuell

| Bereich | Ablauf und praktische Bedeutung |
| --- | --- |
| Discord-Live-Meldungen | `cogs/twitch.py` prüft ungefähr jede Minute die konfigurierten Twitch-Logins über Helix. Pro Discord-Server gibt es einen Twitch-Kanal, einen Zielchannel, einen Nachrichtentext und optional eine Rolle. Die letzte erfolgreich gemeldete Stream-ID liegt in SQLite. |
| Twitch-Anmeldung | `webpanel/twitch_chat.py` bietet eine eigene Anmeldung unter `/twitch`. Botkonto und Broadcaster geben unterschiedliche Berechtigungen frei. Tokens werden verschlüsselt gespeichert; Sessions und OAuth-State als Hash. Änderungen benötigen ein CSRF-Token. |
| Nachrichtenempfang | Twitch sendet `channel.chat.message` per EventSub-Webhook. Der Handler prüft HMAC und Zeitstempel, speichert das Ereignis und bestätigt den Empfang. Die Verarbeitung folgt getrennt davon. |
| Commands und Coins | `twitch_chat/commands.py` prüft AutoMod vor Commands. Message-ID, Buchung und Ergebnis werden gemeinsam in einer Datenbanktransaktion verarbeitet. Eine doppelte Zustellung führt damit nicht zu einer zweiten Coin-Buchung. |
| Chatversand | `twitch_chat/service.py` sendet gespeicherte Ergebnisse über die Chat-API unter der Botidentität. Er prüft auch `is_sent` und Ablehnungsgründe: HTTP 200 allein bedeutet keinen erfolgreichen Versand. AutoMod hat einen eigenen Worker. |
| Timer | Bis zu 20 pro Channel, mit Zeitintervall, Mindestaktivität und optionalem Livestatus. Einstellungen und Fortschritt bleiben über Neustarts erhalten. Pro Channel wird höchstens eine automatische Nachricht pro Minute eingeplant. |
| Discord-Verknüpfung | Verknüpfte Zuschauer verwenden das globale Discord-Guthaben. Lokale Twitch-Coins werden nicht übertragen. Ein Wechsel der Verknüpfung während offener Spiele ist gesperrt. |

Die Wahl von EventSub und Chat-API entspricht Twitchs bevorzugtem Ansatz.
Für gehostete Bots beschreibt Twitch Webhooks mit App-Token und getrennten
Bot-/Broadcaster-Freigaben. Das passt zum vorhandenen Aufbau.
[Twitch Chat](https://dev.twitch.tv/docs/chat/),
[Autorisierung](https://dev.twitch.tv/docs/chat/authenticating/).

Weitere gute Eigenschaften: Shared-Chat-Weiterleitungen führen nicht zu fremden
Coin-Buchungen oder Moderationsaktionen; Spiele überstehen Neustarts;
Chat- und AutoMod-Fehler bleiben getrennt sichtbar. Die User-Tokens werden beim
Start und anschließend stündlich validiert, wie von Twitch beschrieben.
[Token-Validierung](https://dev.twitch.tv/docs/authentication/validate-tokens/).

## Gefundene Fehler und lokale Korrekturen

1. **Doppelte Live-Meldungen beim Speichern oder nach einer Offline-Lücke.**
   Bisher löschte jedes Speichern die letzte Stream-ID, auch bei Änderungen nur
   am Text oder Rollen-Ping. Eine leere Twitch-Antwort löschte sie ebenfalls.
   Dieselbe Stream-ID konnte danach erneut gemeldet werden. Jetzt bleibt die ID
   bei Textänderung, Rollenwechsel, Pause/Fortsetzung und Offline-Antwort erhalten.
   Ein anderer Twitch-Login oder Discord-Zielchannel setzt sie weiterhin zurück;
   eine neue Stream-ID wird regulär gemeldet.

2. **Unnötig viele Live-Abfragen und fehlende Erholung nach HTTP 401.**
   Bisher gab es eine Anfrage pro Discord-Server, auch bei identischen Logins.
   Jetzt werden bis zu 100 verschiedene Logins zusammen abgefragt, ausdrücklich
   mit `first=100`. Bei HTTP 401 wird das App-Token einmal erneuert und die Anfrage
   wiederholt. Ungültige Antwortstrukturen werden als Fehler behandelt.
   Änderungen an der Konfiguration während der Twitch-Anfrage werden vor dem
   Discord-Versand erneut geprüft.
   [Get Streams](https://dev.twitch.tv/docs/api/reference/#get-streams).

3. **Zu große Discord-Embeds nach Platzhalter-Ersetzung.**
   Ein kurzer Text mit vielen `{title}`-Platzhaltern konnte nach Ersetzung das
   Embed-Limit überschreiten und dauerhaft am Versand scheitern. Titel,
   Beschreibung und Kategorie werden jetzt begrenzt. Twitch-Logins akzeptieren
   außerdem nur ASCII-Buchstaben, Ziffern und Unterstriche.

4. **Wiederholungen bei HTTP 429 zu früh.**
   Der Chat-/AutoMod-Versand wartete immer nur fünf Sekunden und konnte seine
   wenigen Wiederholungen vor Ablauf der Sperre verbrauchen. Er berücksichtigt
   jetzt den von Twitch genannten Reset-Zeitpunkt. Das betrifft den
   Zustellungs-Worker; ein gemeinsamer Rate-Limiter für sämtliche API-Aufrufe
   ist damit noch nicht umgesetzt.
   [Twitch API-Limits](https://dev.twitch.tv/docs/api/guide/#twitch-rate-limits).

5. **Ursprünglicher Chattext blieb bei endgültigen Zustellungsfehlern erhalten.**
   Erfolgreiche Zustellungen räumten das Eingangspayload auf, endgültig gescheiterte
   Zustellungen nicht. Jetzt wird es in beiden Fällen entfernt. Bei einer noch
   geplanten Wiederholung bleibt das benötigte Payload bestehen. Gespeicherte
   Command-Ergebnisse und die Verhinderung doppelter Buchungen bleiben erhalten.

Die Duplikatkorrektur deckt die genannten Auslöser ab. Ein Prozessabsturz direkt
zwischen erfolgreichem externem Versand und lokalem Speichern der Bestätigung
kann weiterhin eine doppelte Nachricht verursachen. Die atomare Verarbeitung
der Coins ist davon getrennt.

## Vergleich mit anderen Bots

| Referenz | Dort dokumentiert | Sinnvolle Folgerung für Yami |
| --- | --- | --- |
| [Nightbot Timer](https://docs.nightbot.tv/control-panel/timers) | Intervalle, Mindestanzahl Chatzeilen, Variablen und Command-Aliasse. Aktivität wird in einem Zeitfenster betrachtet. | Intervall plus Aktivität ist schon vorhanden. Yami zählt seit dem letzten Versandversuch; das sollte so verständlich bleiben. Sichere Platzhalter und Command-Verweise wären ein nächster Ausbau. |
| [StreamElements Commands](https://docs.streamelements.com/chatbot/commands/default/command) | Eigene Commands, Aliasse, Rechte sowie getrennte globale und persönliche Cooldowns pro Command. | Besonders nützlich wären frei einstellbare `!discord`, `!socials` oder `!regeln`, anschließend Rechte und Cooldowns pro Command. Aktuell sind die Commands fest programmiert und viele teilen sich denselben Cooldown pro Zuschauer. |
| [StreamElements Timer-Steuerung](https://docs.streamelements.com/chatbot/commands/default/timer) | Moderatoren können Timer im Chat ein- und ausschalten. | Optional eine kleine Moderatorsteuerung anbieten, ohne für jede Pause das Dashboard öffnen zu müssen. |
| [TwitchIO](https://twitchio.dev/en/latest/getting-started/quickstart.html) | Python-Beispiel mit EventSub, separater Botidentität, Tokenverwaltung, SQLite und modularen Commands. | Die grundsätzliche Architektur ist vergleichbar. Ein Bibliothekswechsel wäre ein eigenes Projekt mit Migration und Tests; allein der Vergleich liefert keinen Grund, den funktionierenden Unterbau auszutauschen. |

Bei Nightbot und StreamElements wurden deren öffentliche Dokumentationen
verglichen. Daraus lässt sich ihre interne Serverarchitektur nicht ableiten.

## Empfehlungen der Erstprüfung, nach Nutzen geordnet

Die folgenden Beschreibungen dokumentieren den Zustand vor der beauftragten
Umsetzung. Punkte 1–4 sind mit dem obigen Nachtrag umgesetzt. Die separate
Zuschauer-/AutoMod-Anmeldung aus Punkt 5 bleibt eine mögliche spätere Erweiterung.

1. **Versand unter Last fairer verteilen und sichtbar machen.**
   Aktuell gibt es eine gemeinsame FIFO-Warteschlange für Chatantworten aller
   Channels, mit mindestens 1,6 Sekunden zwischen Versuchen. Nach 120 Sekunden
   werden alte Antworten verworfen; zugehörige Spielbuchungen können schon erfolgt
   sein. Ein aktiver Channel kann dadurch andere verzögern. Vor größerer Nutzung:
   Warteschlangen pro Channel, faire Auswahl, Vorrang für Command-Antworten vor
   Timern und Kennzahlen zu Wartezeit, Verfall und Sendefehlern einführen.
   Die globale Begrenzung ist bewusst konservativ und darf nicht einfach entfernt
   werden: Twitch setzt auch gemeinsame Limits pro Botkonto.
   [Chat-Limits](https://dev.twitch.tv/docs/chat/#rate-limits).

2. **Timer ohne Live-Bedingung von Fehlern der Live-Abfrage entkoppeln.**
   In `Service.schedule_auto_messages` läuft die gemeinsame Live-Abfrage vor dem
   Einplanen aller fälligen Timer. Scheitert sie, fällt dieser komplette Durchlauf
   aus, auch für Nachrichten ohne Live-Bedingung. Künftig sollten nur Timer
   ausgesetzt werden, die einen nicht bestätigten Livestatus benötigen.

3. **Eigene Commands mit Vorschau, Rechten und Cooldowns.**
   Das bringt Streamern direkten Alltagsnutzen. Zunächst reine Textantworten und
   eine kleine Liste sicherer Platzhalter; keine Ausführung beliebiger Skripte.
   Danach Aliasse und Command-spezifische Cooldowns ergänzen.

4. **Statusanzeige genauer trennen.**
   Empfang verbunden, letzte Chat-Antwort erfolgreich, AutoMod funktionsfähig,
   letzte Live-Prüfung und Länge der Warteschlange getrennt anzeigen. Heute
   existieren schon Fehleranzeigen, aber kein vollständiger Überblick über den
   tatsächlichen Nachrichtenfluss. Auch abgelaufene Moderationsaktionen sollten
   im Protokoll einen Endstatus erhalten, statt dort als `pending` stehenzubleiben.

5. **Anmeldung nach Nutzungszweck staffeln.**
   Schon die normale Twitch-Anmeldung fordert derzeit Channel- und
   Moderationsberechtigungen an, auch wenn ein Zuschauer nur Discord verknüpfen
   möchte oder ein Streamer AutoMod nicht nutzt. Eine separate Zuschaueranmeldung
   und spätere zusätzliche AutoMod-Freigabe würden den Einstieg verständlicher
   machen. Dazu müssten Tokenprüfung und Rollenmodell angepasst werden.

Der aktuelle Versand setzt praktisch einen aktiven Botprozess voraus. Vor mehreren
gleichzeitig arbeitenden Instanzen wären eine atomare Reservierung der
Versandaufträge und prozessübergreifende Koordination erforderlich.

## Verifikation

- Ausgangszustand: 95 Twitch-Tests erfolgreich.
- Zusätzliche Regressionstests reproduzierten zunächst die Duplikate und das
  nicht aufgeräumte Payload; nach den Korrekturen erfolgreich.
- Nach der ersten Korrekturrunde 113 Twitch-Tests erfolgreich, einschließlich lokaler HTTP-Testserver
  für Token-Erneuerung, ungültige API-Antworten und Rate-Limit-Header.
- Vollständiger Projektcheck der ersten Korrekturrunde über `bash scripts/check.sh`
  erfolgreich: Python-Kompilierung, 192 Tests, TypeScript-Prüfung und Frontend-Build.
  Der aktuelle Stand nach dem Ausbau steht im Nachtrag am Anfang dieses Dokuments.
- Lokal läuft Python 3.14; Docker und CI sind auf Python 3.12 eingestellt.
  Der lokale Lauf meldet bestehende Deprecation-Warnungen, aber keine Testfehler.
- Der reale OAuth-/EventSub-Rundlauf und die Discord-Zustellung müssen nach
  einem Deployment mit den vorgesehenen Konten geprüft werden.
