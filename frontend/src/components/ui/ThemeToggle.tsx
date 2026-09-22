import { useTheme } from "../../lib/theme";
import { Icon } from "../Icon";

/** Kompakter Dark/Light-Umschalter. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      title={dark ? "Light-Modus" : "Dark-Modus"}
      aria-label="Theme umschalten"
      className={`grid h-9 w-9 place-items-center rounded-full border border-border-strong bg-surface-2 text-muted transition-colors hover:border-accent/50 hover:text-accent ${className}`}
    >
      <Icon name={dark ? "sun" : "moon"} size={17} />
    </button>
  );
}
