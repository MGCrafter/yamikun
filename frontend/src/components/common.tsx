import type { ReactNode } from "react";
import { motion } from "motion/react";
import { Icon } from "./Icon";

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="page-head"
    >
      <span className="bar" />
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="sub">{subtitle}</div>}
      </div>
    </motion.div>
  );
}

export function Panel({
  title,
  children,
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
      className={`panel mb-6 ${className ?? ""}`}
    >
      {title && <h2 className="mb-5 text-[18px] font-bold tracking-tight">{title}</h2>}
      {children}
    </motion.section>
  );
}

export function SectionHeader({ children }: { children: ReactNode }) {
  return <div className="s-head mt-7">{children}</div>;
}

export function EmptyState({ children, icon = "box" }: { children: ReactNode; icon?: string }) {
  return (
    <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} className="empty-state">
      <div className="es-ic">
        <Icon name={icon} size={24} />
      </div>
      <div className="max-w-sm text-[0.92rem] text-muted">{children}</div>
    </motion.div>
  );
}

export function InfoBanner({ children }: { children: ReactNode }) {
  return (
    <div className="note">
      <span className="ni">
        <Icon name="alert" size={18} />
      </span>
      <span>{children}</span>
    </div>
  );
}

export function Spinner() {
  return (
    <div className="grid place-items-center py-24">
      <div className="relative h-9 w-9">
        <div className="absolute inset-0 animate-spin-slow rounded-full border-2 border-border-strong border-t-accent" />
        <div className="absolute inset-0 rounded-full bg-accent/20 blur-lg" />
      </div>
    </div>
  );
}
