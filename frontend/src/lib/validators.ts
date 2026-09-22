// Zentrale, wiederverwendbare Feld-Validatoren für alle Panel-Formulare.
// Ein Validator nimmt einen Wert und gibt entweder einen Fehlertext (string)
// oder null (gültig) zurück. So lassen sich Validatoren beliebig kombinieren.
//
// Discord-Limits (Stand 2024): Nachricht 2000, Embed-Titel 256, Embed-Beschr. 4096.
export const DISCORD = {
  MESSAGE: 2000,
  EMBED_TITLE: 256,
  EMBED_DESC: 4096,
  NICK: 32,
} as const;

export type Validator = (value: unknown) => string | null;

const isBlank = (v: unknown) =>
  v == null || (typeof v === "string" && v.trim() === "");

/** Pflichtfeld: darf nicht leer/whitespace sein. */
export const required =
  (msg = "Dieses Feld ist erforderlich."): Validator =>
  (v) =>
    isBlank(v) ? msg : null;

/** Höchstlänge (Discord-Limits). Leere Werte ignoriert (required separat). */
export const maxLen =
  (n: number, msg?: string): Validator =>
  (v) =>
    typeof v === "string" && v.length > n
      ? msg ?? `Maximal ${n} Zeichen (aktuell ${v.length}).`
      : null;

/** Discord-Snowflake-ID (15–21 Ziffern). Leere Werte ignoriert. */
export const snowflake =
  (msg = "Bitte eine gültige Discord-ID angeben (nur Ziffern)."): Validator =>
  (v) =>
    !isBlank(v) && !/^\d{15,21}$/.test(String(v).trim()) ? msg : null;

/** http(s)-URL. Verhindert u. a. javascript:/data:-Schemata. Leer ignoriert. */
export const httpUrl =
  (msg = "Bitte eine gültige http(s)-Bild-URL angeben."): Validator =>
  (v) => {
    if (isBlank(v)) return null;
    try {
      const u = new URL(String(v).trim());
      return u.protocol === "http:" || u.protocol === "https:" ? null : msg;
    } catch {
      return msg;
    }
  };

/** Ganzzahl in [min, max]. Leer ignoriert (required separat einsetzen). */
export const intRange =
  (min: number, max: number, msg?: string): Validator =>
  (v) => {
    if (isBlank(v)) return null;
    const n = Number(v);
    if (!Number.isInteger(n)) return msg ?? "Bitte eine ganze Zahl angeben.";
    if (n < min || n > max)
      return msg ?? `Wert muss zwischen ${min} und ${max} liegen.`;
    return null;
  };

/** Führt alle Validatoren der Reihe nach aus; erster Fehler gewinnt. */
export function runValidators(
  value: unknown,
  validators: Validator[] = [],
): string | null {
  for (const v of validators) {
    const err = v(value);
    if (err) return err;
  }
  return null;
}
