import { motion } from "motion/react";
import { Link, Navigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/common";

export default function GuildPicker() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!me?.authenticated) return <Navigate to="/" replace />;

  const guilds = me.guilds ?? [];
  // Keine Admin-Rechte? -> persönliches Dashboard.
  if (guilds.length === 0) return <Navigate to="/me" replace />;
  // Nur ein Admin-Server? Direkt rein.
  if (guilds.length === 1) return <Navigate to={`/g/${guilds[0].id}/overview`} replace />;

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <div className="mb-8 flex items-center gap-3">
        <img src="/assets/YamiKun.webp" alt="" className="h-11 w-11 rounded-xl object-cover" />
        <div>
          <h1 className="font-display text-2xl font-bold">Server wählen</h1>
          <p className="text-sm text-muted">Angemeldet als {me.username}</p>
        </div>
      </div>

      <div className="grid gap-3">
        {guilds.map((g, i) => (
          <motion.div
            key={g.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <Link
              to={`/g/${g.id}/overview`}
              className="flex items-center justify-between rounded-md border border-border bg-surface px-5 py-4 text-lg font-semibold shadow-glow transition hover:border-accent/50"
            >
              {g.name}
              <Icon name="arrow" size={18} />
            </Link>
          </motion.div>
        ))}
      </div>

      <div className="mt-8 flex items-center gap-5">
        <Link to="/me" className="inline-flex items-center gap-2 text-sm text-muted hover:text-accent">
          <Icon name="box" size={16} /> Mein Dashboard
        </Link>
        <a href="/logout" className="inline-flex items-center gap-2 text-sm text-faint hover:text-danger">
          <Icon name="logout" size={16} /> Abmelden
        </a>
      </div>
    </div>
  );
}
