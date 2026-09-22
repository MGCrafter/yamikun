import { useEffect, useRef, useState } from "react";
import { fmtNum } from "../../lib/utils";

// Zählt von 0 zum Zielwert hoch (Bento-Stat-Animation).
export function AnimatedNumber({ value, format }: { value: number; format?: boolean }) {
  const [display, setDisplay] = useState(0);
  const ref = useRef<number>();

  useEffect(() => {
    const start = performance.now();
    const duration = 900;
    const from = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setDisplay(Math.round(from + (value - from) * eased));
      if (t < 1) ref.current = requestAnimationFrame(tick);
    };
    ref.current = requestAnimationFrame(tick);
    return () => {
      if (ref.current) cancelAnimationFrame(ref.current);
    };
  }, [value]);

  return <>{format ? fmtNum(display) : display}</>;
}
