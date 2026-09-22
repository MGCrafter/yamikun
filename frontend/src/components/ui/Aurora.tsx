import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

// Aceternity-Stil: animierter Aurora-/Verlaufs-Hintergrund für die Landing-Page.
export function Aurora({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("relative isolate overflow-hidden bg-bg", className)}>
      {/* Dezenter Aurora-Schimmer, nur im oberen Bereich, stark weichgezeichnet. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[55vh] overflow-hidden opacity-25 blur-[70px]">
        <div
          className="absolute -inset-[10%] animate-aurora will-change-transform
            [background-image:repeating-linear-gradient(100deg,#c5f04a_8%,#7aa0ff_22%,#c07bff_36%,#c5f04a_50%)]
            [background-size:300%_200%] [background-position:50%_50%]
            [--m:linear-gradient(to_bottom,black,transparent_75%)]
            [-webkit-mask-image:var(--m)] [mask-image:var(--m)]"
        />
      </div>
      {/* Vignette, damit Text klar lesbar bleibt */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-bg/30 via-transparent to-bg" />
      <div className="relative">{children}</div>
    </div>
  );
}
