import type { ReactNode } from "react";

// Einheitlicher Formular-Feld-Wrapper: Label, optionaler Pflicht-Stern (*),
// Inline-Fehlermeldung (rot, role="alert") und optionaler Hinweistext.
// Das eigentliche Eingabe-Element (input/select/textarea) kommt als children.
export function Field({
  label,
  required,
  error,
  hint,
  htmlFor,
  className,
  children,
}: {
  label?: string;
  required?: boolean;
  error?: string;
  hint?: ReactNode;
  htmlFor?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`fieldwrap ${error ? "has-error" : ""} ${className ?? ""}`}>
      {label && (
        <label className="label" htmlFor={htmlFor}>
          {label}
          {required && (
            <span className="req" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      {children}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="field-hint">{hint}</p>
      ) : null}
    </div>
  );
}
