# 📋 TODO – Yumikun Bot (Karten-Features)

Stand: 2026-05-30. Dieses Dokument ist die Arbeitsgrundlage und in anderen Chats nutzbar.

## Entscheidungen (fix)
- **Booster für Gamecards:** pro Spiel ein eigenes Pack.
- **Server-übergreifend:** **alles global** (Option A) – ein Kartenpool, ein Inventar, eine Coin-Balance pro User über alle Server hinweg.
- **Reihenfolge:** erst das globale Fundament, dann bauen alle Features direkt darauf auf (vermeidet Doppelarbeit).

## Ist-Zustand (Kurz)
- Zwei Kartensysteme: `cogs/gamecards.py` (erspielte Karten, `card_inventory`/`custom_cards`) & `cogs/booster.py` (Yami-Karten, `server_inventory`/`server_cards`).
- Trading nur in `gamecards.py` (`TradeView` + `db.trade_cards`), 1:1 ohne Tokens.
- Booster nur für Yami-Karten (`PACKS` standard/premium), nicht für erspielte Gamecards.
- Webpanel (`cogs/webpanel.py`): Overview, Cards, Games & Channel.
- **Alles ist `guild_id`-getrennt** → Global-Umstellung ist die Grundlage für den Rest.

---

## Phase 1 – Globales Datenmodell (Fundament) 🏗️
Betroffen: `db.py`, alle Karten-Cogs.
- [ ] Schema-Entscheidung: globale Tabellen ohne `guild_id` (bzw. `guild_id = 0` als „global"-Marker, weniger Migrationsaufwand).
- [ ] Karten-Katalog global: `custom_cards` & `server_cards` → ein Pool für alle Server.
- [ ] Inventare global: `card_inventory` & `server_inventory` → pro User, serverunabhängig.
- [ ] Coins global: `levels.coins` zu globaler Balance pro User (XP/Level evtl. weiter pro Server – entscheiden).
- [ ] DB-Helper umstellen: `guild_id`-Parameter entfernen/ignorieren, wo global.
- [ ] **Migration** der bestehenden `bot.db`: vorhandene Karten/Coins zusammenführen (bei Duplikaten über Server: aufsummieren). Backup vorher.
- [ ] Reward-Spiele (`reward_games`) & Channel-Config: global oder pro Server? → vermutlich pro Server lassen (Spiele/Channel sind serverspezifisch). Klären.

## Phase 2 – Karten aus dem Inventar entfernen 🗑️
Betroffen: `db.py`, `cogs/gamecards.py`, `cogs/booster.py`.
- [ ] DB: `remove_card(user_id, card_id, amount)` (+ Pendant Server-/Yami-Karten).
- [ ] `/gamecards remove karte:… [anzahl]` mit `_owned_card_autocomplete`.
- [ ] Bestätigungs-Button vor dem Löschen (versehentliches Löschen vermeiden).
- [ ] Optional: `/booster remove` für Yami-Karten.

## Phase 3 – Booster-Packs für Gamecards (pro Spiel, teurer) 📦
Betroffen: `cogs/booster.py`, `db.py`.
- [ ] Pro-Spiel-Pack: Pack-Typ trägt das Spiel (z.B. `gamecard_<spiel>`), zieht nur aus dem Katalog dieses Spiels.
- [ ] Preis deutlich höher als Yami-Packs (Wert festlegen, z.B. 8.000+).
- [ ] `db.add_packs/consume_pack` (Tabelle `packs` ist generisch) wiederverwenden.
- [ ] Roll-Funktion aus Gamecard-Katalog (`list_custom_cards_for_game`).
- [ ] `/booster buy` & `/booster open`: Spiel-Auswahl ergänzen (Autocomplete auf Spiele mit Karten).

## Phase 4 – Trading mit Tokens (Karten kaufen/verkaufen) 🪙
Betroffen: `cogs/gamecards.py` (`TradeView`), `db.py`.
- [ ] `db.trade_cards` um optionalen Coin-Betrag erweitern – atomar mit dem Kartentausch.
- [ ] `TradeView`: Tokens als Teil des Angebots eingeben (eine oder beide Seiten), Balance-Check vor Bestätigung.
- [ ] Reiner Kauf-Modus (Karte gegen Coins, ohne Gegenkarte) = „Karte abkaufen".
- [ ] Race-Condition absichern: Balance erneut prüfen beim finalen Bestätigen.

## Phase 5 – Webpanel ausbauen 🖥️
Betroffen: `cogs/webpanel.py`.
- [ ] Seite **Yami-Karten** (add/delete, analog zu Cards) → `list/add/remove_server_card`.
- [ ] Seite **Booster-Konfiguration**: Preise/Gewichte editierbar statt hartcodiert in `PACKS`.
- [ ] Seite **Mitglieder/Economy**: Coins ansehen & anpassen, Leaderboard.
- [ ] Seite **Inventare**: wer besitzt welche Karten (+ Karten entfernen, siehe Phase 2).
- [ ] Optional: Statistiken (Drops/Tag, beliebteste Karten).

---

## Offene Fragen
- XP/Level: global oder pro Server? (Coins werden global.)
- Reward-Spiele & Karten-Channel: pro Server lassen?
- Konkreter Preis für Gamecard-Packs.
