# 🤖 Yamikun — Server-Guide (Schnellüberblick)

Alles Wichtige auf einen Blick — für Mitglieder **und** Server-Admins. Tippe im Chat
**`/help`** für die vollständige, interaktive Befehlsliste.

---

## ⚡ Was kann der Bot?

| Bereich | Kurz gesagt |
|---|---|
| 🎴 **Sammelkarten** | Karten durchs **Spielen** verdienen, tauschen, sammeln |
| 📦 **Booster-Packs** | Packs kaufen/erspielen & öffnen → zufällige Karten ([Chancen](BOOSTER_CHANCEN.md)) |
| 💰 **Economy** | Coins über `/daily`, Spielen & Gewinnen — überweisen mit `/pay` |
| 📊 **Leveling** | XP aus Nachrichten & Voice, Level-Ups mit Coin-Belohnung |
| 🎮 **Games** | Blackjack, Slots, Roulette, Coinflip |
| 👥 **Social** | Freunde, Friendship-Level, GIF-Aktionen, Heiraten |
| 🎯 **LFG** | Gruppensuche mit Join-Buttons |
| 🎫 **Tickets** | Privater Support per Auswahlmenü → eigener Thread, Claim/Close, Transcript |
| 🛠️ **Server-Tools** | Reaction Roles, Willkommensnachrichten, Audit-Log, Auto-Delete, Announcer |
| 🖥️ **Webpanel** | Alles bequem im Browser verwalten (Discord-Login) |

> **Wichtig:** Coins, XP, Level, Karten & Packs sind **serverübergreifend pro User** —
> eine Identität über alle Server. Pro Server bleiben nur Einstellungen (Channels,
> getrackte Spiele, Reaction Roles, Welcome, Audit).

---

## 👤 Für Mitglieder — die wichtigsten Befehle

```
/help                  Alle Befehle (interaktiv)
/daily                 Tägliche Coins (mit Streak-Bonus)
/rank   ·  /leaderboard   Dein Level · Top 10
/profile               Deine Profilseite
/gamecards             Deine erspielten Karten
/booster buy|open      Yami-Packs kaufen & öffnen
/booster opengame      Erspielte Spiel-Booster öffnen  (✨ Godpack-Chance!)
/trade @user           Karten tauschen oder mit Coins kaufen
/coinflip · /blackjack · /slots · /roulette   Glücksspiele
```

**Hilfe brauchen?** Im Support-Channel im **Ticket-Panel** ein Thema wählen — es öffnet
sich ein **privater Thread** nur für dich und das Team. Erledigt? Button **Schließen**.

**Karten verdienen:** Spiel einfach eines der konfigurierten Spiele — pro **30 Min**
Spielzeit gibt es automatisch einen **Spiel-Booster** (max. 12/Tag). Öffnen mit
`/booster opengame`. → Details & Chancen: **[BOOSTER_CHANCEN.md](BOOSTER_CHANCEN.md)**

---

## 🛠️ Für Admins — Einrichtung in 5 Minuten

1. **Bot einladen** mit Scope `bot` + `applications.commands`.
2. Im **Discord Developer Portal → Bot → Privileged Gateway Intents** aktivieren:
   - ✅ **Message Content Intent** (Pflicht)
   - ✅ **Server Members Intent** (Pflicht — Welcome, Audit, Reaction Roles)
   - ✅ **Presence Intent** (optional — nur für Karten-Rewards fürs Spielen)
3. **Slash-Commands** erscheinen automatisch (global bis ~1 h, oder sofort via `GUILD_ID`).
4. **Karten-Rewards einrichten:**
   - `/gamereward addgame <Spiel>` — ein Spiel tracken
   - `/gamereward addcard <Spiel> <Name> <Seltenheit> <Bild-URL>` — Karten anlegen
   - `/gamereward setchannel #channel` — wohin Karten-Drops gemeldet werden
   > Ohne Karten droppt nichts — es gibt **kein** eingebautes Karten-Set.
5. **Optional:** `/level setchannel`, Reaction Roles / Welcome / Audit-Log / **Tickets** im **Webpanel**.
6. **Ticket-System (optional):** `/ticket setrole @support`, dann `/ticket panel #support`
   posten. Themen per `/ticket category add …` oder im Webpanel anlegen, Transcripts mit
   `/ticket setlog #ticket-logs`.
   > Der Bot braucht im Panel-Channel **Private Threads erstellen** + **Threads verwalten**;
   > die Support-Rolle sollte **Threads verwalten** haben, um alle Tickets zu sehen.

### Wichtige Admin-Befehle
```
/gamereward addgame|removegame|listgames        Reward-Spiele verwalten
/gamereward addcard|removecard|listcards         Karten pro Spiel verwalten
/gamereward givecard @user <karte>               Karte direkt vergeben
/yamicard add|remove|list                        Yami-Karten (für Kauf-Packs)
/reactionrole add|remove|list                    Rollen per Reaktion
/ticket panel|setrole|setlog|category            Ticket-System einrichten
/level setchannel · /level coins @user <coins>    Leveling-Admin
/purge <anzahl> · /say <text>                     Moderation
```

---

## 🖥️ Webpanel

Im Browser verwalten (Login über Discord, nur mit Rechten **Server verwalten**):
**Sammelkarten & Bilder hochladen · Yami-Karten · Economy/Coins · Inventare ·
Reaction Roles · Willkommensnachrichten (inkl. Banner) · Audit-Log · Tickets ·
Spiele & Drop-Channel.**

---

## 💎 Seltenheiten

⚪ Common · 🟢 Uncommon · 🔵 Rare · 🟣 Epic · 🟡 Legendary · 🔴 Mythic

Die genauen Pack-Chancen, das **Godpack** und alles Drumherum:
👉 **[BOOSTER_CHANCEN.md](BOOSTER_CHANCEN.md)**

---

*Fragen? `/help` im Chat zeigt jederzeit alle Befehle mit Erklärung.*
