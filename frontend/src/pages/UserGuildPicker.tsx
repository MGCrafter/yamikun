import { motion } from "motion/react";
import { Link, Navigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/common";

// Server-Auswahl für das persönliche Dashboard (alle Server, in denen man Mitglied ist).
export default function UserGuildPicker() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!me?.authenticated) return <Navigate to="/" replace />;

  const guilds = me.member_guilds ?? [];
  if (guilds.length === 0) return <Navigate to="/?error=no_access" replace />;
  if (guilds.length === 1) return <Navigate to={`/u/${guilds[0].id}`} replace />;

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <div className="mb-8 flex items-center gap-3">
        <img src="/assets/YamiKun.webp" alt="" className="h-11 w-11 rounded-xl object-cover" />
        <div>
          <h1 className="font-display text-2xl font-bold">Mein Dashboard</h1>
          <p className="text-sm text-muted">Wähle einen Server, {me.username}</p>
        </div>
      </div>
      <div className="grid gap-3">
        {guilds.map((g, i) => (
          <motion.div key={g.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Link
              to={`/u/${g.id}`}
              className="flex items-center justify-between rounded-md border border-border bg-surface px-5 py-4 text-lg font-semibold shadow-glow transition hover:border-accent/50"
            >
              {g.name}
              <Icon name="arrow" size={18} />
            </Link>
          </motion.div>
        ))}
      </div>
      <a href="/logout" className="mt-8 inline-flex items-center gap-2 text-sm text-faint hover:text-danger">
        <Icon name="logout" size={16} /> Abmelden
      </a>
    </div>
  );
}
