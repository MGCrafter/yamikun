import { useState } from "react";
import { runValidators, type Validator } from "./validators";

// Nicht-invasiver Validierungs-Hook: die Page behält ihre eigenen useState-Felder.
// Man übergibt die AKTUELLEN Werte + ein Schema (Feldname → Validatoren).
//
// Verhalten (wie abgestimmt): Fehler beim Absenden (validateAll) und beim
// Verlassen eines Felds (blur/onBlur). showError() zeigt einen Fehler erst,
// wenn das Feld berührt wurde oder ein Submit-Versuch lief.
//
// Beispiel:
//   const v = useValidation({ channel: channelId, content }, {
//     channel: [required("Bitte einen Channel wählen.")],
//     content: [required("Bitte einen Inhalt eingeben."), maxLen(DISCORD.MESSAGE)],
//   });
//   ...
//   <Field label="Channel" required error={v.showError("channel")}>
//     <select onBlur={v.blur("channel")} ... />
//   </Field>
//   <button disabled={busy || !v.isValid} onClick={() => { if (!v.validateAll()) return; submit(); }}>
export type Schema<T> = Partial<Record<keyof T, Validator[]>>;

export function useValidation<T extends Record<string, unknown>>(
  values: T,
  schema: Schema<T>,
) {
  const [touched, setTouched] = useState<Partial<Record<keyof T, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);

  const fieldError = (k: keyof T): string | null =>
    runValidators(values[k], schema[k] ?? []);

  // onBlur-Handler-Fabrik: <input onBlur={v.blur("name")} />
  const blur = (k: keyof T) => () =>
    setTouched((t) => ({ ...t, [k]: true }));

  // Vor dem Absenden aufrufen; gibt true zurück, wenn alles gültig ist.
  const validateAll = (): boolean => {
    setSubmitted(true);
    return Object.keys(schema).every((k) => !fieldError(k as keyof T));
  };

  // Insgesamt gültig? (Für disabled am Submit-Button.)
  const isValid = Object.keys(schema).every((k) => !fieldError(k as keyof T));

  // Fehler nur zeigen, wenn berührt ODER Submit versucht wurde.
  const showError = (k: keyof T): string | undefined =>
    touched[k] || submitted ? (fieldError(k) ?? undefined) : undefined;

  const reset = () => {
    setTouched({});
    setSubmitted(false);
  };

  return { blur, validateAll, isValid, showError, reset };
}
