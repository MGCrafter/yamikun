import { cn } from "../../lib/utils";

/**
 * Discord-Profilbild mit Fallback auf die Initiale.
 * `online` zeigt zusätzlich einen grünen Status-Punkt.
 */
export function Avatar({
  src,
  name,
  size = 40,
  online = false,
  className,
}: {
  src?: string | null;
  name?: string;
  size?: number;
  online?: boolean;
  className?: string;
}) {
  const initial = (name ?? "?").charAt(0).toUpperCase();
  const ring = "ring-2 ring-accent/40";
  return (
    <span className="relative inline-block flex-none" style={{ width: size, height: size }}>
      {src ? (
        <img
          src={src}
          alt={name ?? ""}
          loading="lazy"
          className={cn("h-full w-full rounded-full object-cover", ring, className)}
          onError={(e) => ((e.currentTarget.style.display = "none"))}
        />
      ) : (
        <span
          className={cn(
            "grid h-full w-full place-items-center rounded-full bg-gradient-to-br from-accent to-violet font-bold text-accent-ink",
            ring,
            className,
          )}
          style={{ fontSize: size * 0.4 }}
        >
          {initial}
        </span>
      )}
      {online && (
        <span className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full border-2 border-bg bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
      )}
    </span>
  );
}
