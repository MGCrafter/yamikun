import { Icon } from "../Icon";

// Sauberer Zahl-Stepper (−/+) ohne native Browser-Pfeile.
export function NumberStepper({
  value,
  onChange,
  min = 1,
  max = 9999,
}: {
  value: string;
  onChange: (v: string) => void;
  min?: number;
  max?: number;
}) {
  const num = parseInt(value, 10);
  const clamp = (n: number) => String(Math.max(min, Math.min(max, n)));
  const step = (delta: number) => onChange(clamp((isNaN(num) ? min : num) + delta));

  return (
    <span className="inline-flex items-center overflow-hidden rounded-[var(--r-xs)] border border-border bg-inset">
      <button
        type="button"
        tabIndex={-1}
        onClick={() => step(-1)}
        className="grid h-9 w-7 place-items-center text-muted transition-colors hover:bg-surface-2 hover:text-accent"
      >
        <Icon name="minus" size={14} />
      </button>
      <input
        value={value}
        inputMode="numeric"
        onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={() => value && onChange(clamp(parseInt(value, 10) || min))}
        className="w-9 bg-transparent text-center font-mono text-[14px] text-txt outline-none"
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={() => step(1)}
        className="grid h-9 w-7 place-items-center text-muted transition-colors hover:bg-surface-2 hover:text-accent"
      >
        <Icon name="plus" size={14} />
      </button>
    </span>
  );
}
