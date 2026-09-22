# 🎴 Booster-Packs & Drop-Chancen

Alles, was du über Booster-Packs wissen musst: **wie du sie bekommst** und **welche
Karten mit welcher Wahrscheinlichkeit** drin sind.

> Hinweis: Die Karten selbst legt **jeder Server selbst** an (Bild, Name, Seltenheit).
> Die folgenden Chancen beziehen sich auf die **Seltenheit** der gezogenen Karte —
> welche konkrete Karte du innerhalb einer Seltenheit ziehst, ist gleichverteilt.

---

## 1. Wie bekomme ich Booster-Packs?

| Weg | Befehl | Kosten | Was man bekommt |
|---|---|---|---|
| **Yami-Pack kaufen** | `/booster buy standard` | 2.000 🪙 | Standard-Pack (5 Karten) |
| **Yami-Pack kaufen** | `/booster buy premium` | 5.000 🪙 | Premium-Pack (5 Karten, bessere Chancen) |
| **Spiel-Booster kaufen** | `/booster buygame <spiel>` | 200.000 🪙 | Spiel-Booster (5 Karten des Spiels) |
| **Spiel-Booster erspielen** | — (automatisch) | gratis | 1 Spiel-Booster pro **30 Min** Spielzeit, max. **12/Tag** |

**Erspielen:** Wer ein konfiguriertes Spiel spielt, bekommt automatisch Spiel-Booster
(Standard: 1 pro 30 Min, max. 12 pro Tag — pro Spiel vom Server einstellbar). Das
funktioniert nur, wenn der Bot die Aktivität sieht (**Presence Intent**) und das Spiel
Karten hat.

**Öffnen:** `/booster open <typ>` (Yami) bzw. `/booster opengame <spiel>` (Spiel-Booster).
Die Karten werden **einzeln nacheinander aufgedeckt — die seltenste zuletzt** 🎉

---

## 2. Seltenheiten

| Seltenheit | Symbol |
|---|---|
| Common | ⚪ |
| Uncommon | 🟢 |
| Rare | 🔵 |
| Epic | 🟣 |
| Legendary | 🟡 |
| Mythic | 🔴 |

---

## 3. Drop-Chancen pro Karte

Jedes Pack enthält **5 Karten**. Die Chancen gelten **pro gezogener Karte**.

### 📦 Standard-Pack (2.000 🪙)
| Seltenheit | Chance |
|---|---|
| ⚪ Common | ~49,9 % |
| 🟢 Uncommon | ~27,9 % |
| 🔵 Rare | ~15,0 % |
| 🟣 Epic | ~6,0 % |
| 🟡 Legendary | ~1,0 % |
| 🔴 Mythic | ~0,2 % |

### ✨ Premium-Pack (5.000 🪙)
| Seltenheit | Chance |
|---|---|
| ⚪ Common | 20 % |
| 🟢 Uncommon | 30 % |
| 🔵 Rare | 30 % |
| 🟣 Epic | 15 % |
| 🟡 Legendary | 4 % |
| 🔴 Mythic | 1 % |

### 🎴 Spiel-Booster (erspielt oder 200.000 🪙)
Gleiche Verteilung wie das Standard-Pack, zieht aber aus dem **Karten-Pool des
jeweiligen Spiels**:
| Seltenheit | Chance |
|---|---|
| ⚪ Common | ~49,9 % |
| 🟢 Uncommon | ~27,9 % |
| 🔵 Rare | ~15,0 % |
| 🟣 Epic | ~6,0 % |
| 🟡 Legendary | ~1,0 % |
| 🔴 Mythic | ~0,2 % |

---

## 4. ✨ Godpack (nur Spiel-Booster)

Beim Öffnen eines **Spiel-Boosters** gibt es eine **sehr geringe Chance** auf ein
**Godpack** — statt 5 normaler Karten bekommst du **genau 1 Karte**, garantiert
**Legendary oder Mythic**.

| | Chance |
|---|---|
| **Godpack überhaupt** (pro geöffnetem Spiel-Booster) | **0,2 %** (1 von 500) |
| → davon 🟡 **Legendary** | 97 % |
| → davon 🔴 **Mythic** | 3 % |

> Hat das Spiel keine Legendary-/Mythic-Karten, öffnet sich stattdessen ein normales Pack.

---

## 5. Chance auf ≥ 1 seltene Karte pro Pack (5 Karten)

Da ein Pack 5 Karten zieht, ist die Chance auf „mindestens eine" seltene Karte höher:

| Pack | ≥ 1 Legendary+ | ≥ 1 Mythic |
|---|---|---|
| 📦 Standard / 🎴 Spiel | ~5,9 % | ~1,0 % |
| ✨ Premium | ~22,6 % | ~4,9 % |

---

## Kleingedrucktes

- **Nur vorhandene Seltenheiten zählen:** Hat ein Server (oder ein Spiel) z. B. keine
  Mythic-Karten, wird diese Seltenheit übersprungen und die Chancen verteilen sich
  auf die tatsächlich vorhandenen Seltenheiten neu. Die obigen Prozente gelten also
  für den Fall, dass **alle** Seltenheiten existieren.
- **Karten sind serverübergreifend pro User:** Dein Karten-Inventar und das Tageslimit
  gelten über alle Server hinweg (eine Identität).
- Werte können vom Server-Team angepasst werden (Intervall & Tageslimit pro Spiel).
