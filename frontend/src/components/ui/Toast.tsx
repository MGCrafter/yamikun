import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Icon } from "../Icon";

type ToastKind = "ok" | "err" | "loading";
type Toast = { id: number; kind: ToastKind; text: string };
type Ctx = {
  /** Zeigt einen Toast und gibt seine id zurück. "loading" bleibt bis zum update() stehen. */
  push: (kind: ToastKind, text: string) => number;
  /** Wandelt einen bestehenden Toast um (z.B. loading → ok/err). */
  update: (id: number, kind: ToastKind, text: string) => void;
};
const ToastContext = createContext<Ctx>({ push: () => 0, update: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  // loading-Toasts laufen nicht automatisch ab — sie warten auf update().
  const autoDismiss = useCallback((id: number, kind: ToastKind) => {
    if (kind === "loading") return;
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3800);
  }, []);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    autoDismiss(id, kind);
    return id;
  }, [autoDismiss]);

  const update = useCallback((id: number, kind: ToastKind, text: string) => {
    setToasts((t) => t.map((x) => (x.id === id ? { ...x, kind, text } : x)));
    autoDismiss(id, kind);
  }, [autoDismiss]);

  return (
    <ToastContext.Provider value={{ push, update }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex flex-col gap-2.5">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: 40, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, scale: 0.95 }}
              transition={{ type: "spring", stiffness: 360, damping: 26 }}
              className={`pointer-events-auto flex items-center gap-2.5 rounded-xl border px-4 py-3 text-sm font-medium backdrop-blur ${
                t.kind === "ok"
                  ? "border-accent/40 bg-accent/[0.12] text-accent"
                  : t.kind === "err"
                  ? "border-danger/40 bg-danger/[0.13] text-[#ffb4b4]"
                  : "border-border-strong bg-bg/70 text-muted"
              }`}
            >
              <Icon
                name={t.kind === "ok" ? "check" : t.kind === "err" ? "alert" : "loader"}
                size={17}
                className={t.kind === "loading" ? "animate-spin" : undefined}
              />
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
