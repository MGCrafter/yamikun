import { useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useAuth } from "../lib/auth";
import { useApiData } from "../lib/useApiData";
import { Avatar } from "../components/ui/Avatar";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Icon } from "../components/Icon";
import { EmptyState, Spinner } from "../components/common";


type Progress = { current: number; target: number; percent: number };
type Achievement = {
  id: string;
  title: string;
  description: string;
  category: string;
  emoji: string;
  secret: boolean;
  unlocked: boolean;
  unlocked_at: number | null;
  progress: Progress | null;
  hint: string | null;
};
type Person = {
  id: string;
  username: string;
  avatar: string | null;
  unlocked_count: number;
  friendship_xp?: number;
  achievements: Achievement[];
};
type AchievementData = {
  guild: { id: string; name: string };
  user: Person;
  friends: Person[];
};


function AchievementCard({ item, index }: { item: Achievement; index: number }) {
  const lockedSecret = item.secret && !item.unlocked;
  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.035, 0.35) }}
      className={`relative overflow-hidden rounded-2xl border p-5 transition-colors ${
        item.unlocked
          ? "border-amber-400/35 bg-gradient-to-br from-amber-400/[0.12] to-violet-500/[0.06]"
          : "border-white/[0.07] bg-white/[0.025]"
      }`}
    >
      {item.unlocked && <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-300 to-transparent" />}
      <div className="flex items-start gap-4">
        <div className={`grid h-14 w-14 shrink-0 place-items-center rounded-2xl text-2xl ${
          item.unlocked ? "bg-amber-300/15 shadow-[0_0_28px_rgba(251,191,36,.12)]" : "bg-white/[0.05] grayscale"
        }`}>
          {item.emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h3 className={`font-display text-[16px] font-bold ${item.unlocked ? "text-amber-100" : "text-muted"}`}>
              {item.title || "Geheimes Achievement"}
            </h3>
            {item.secret && (
              <span className="rounded-full border border-violet-400/20 bg-violet-400/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.16em] text-violet-300">
                geheim
              </span>
            )}
          </div>
          <p className="text-[13px] leading-relaxed text-faint">{item.description}</p>

          {item.unlocked ? (
            <div className="mt-3 flex items-center gap-2 text-[11px] font-semibold text-amber-300">
              <Icon name="check" size={13} /> Freigeschaltet
              {item.unlocked_at && (
                <span className="font-normal text-faint">
                  · {new Date(item.unlocked_at * 1000).toLocaleDateString("de-DE")}
                </span>
              )}
            </div>
          ) : item.progress ? (
            <div className="mt-4">
              <div className="mb-1.5 flex justify-between font-mono text-[10px] text-faint">
                <span>{item.progress.current.toLocaleString("de-DE")} / {item.progress.target.toLocaleString("de-DE")}</span>
                <span>{item.progress.percent}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-black/30">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-violet-500 to-amber-300 transition-all duration-700"
                  style={{ width: `${item.progress.percent}%` }}
                />
              </div>
            </div>
          ) : (
            <div className="mt-3 space-y-2">
              <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-faint">
                <Icon name="shield" size={12} /> Verborgene Bedingung
              </div>
              {item.hint && (
                <div className="rounded-xl border border-amber-300/15 bg-amber-300/[0.06] px-3 py-2 text-[12px] leading-relaxed text-amber-100/80">
                  <span className="mr-1.5">💡</span><strong>Tipp:</strong> {item.hint}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {lockedSecret && <div className="pointer-events-none absolute -bottom-16 -right-12 h-36 w-36 rounded-full bg-violet-500/[0.07] blur-2xl" />}
    </motion.article>
  );
}


export default function Achievements() {
  const { gid } = useParams();
  const { me, loading: authLoading } = useAuth();
  const { data, loading } = useApiData<AchievementData>(`/api/u/${gid}/achievements`);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const people = data ? [data.user, ...data.friends] : [];
  const selected = people.find((person) => person.id === selectedId) ?? data?.user;
  const grouped = useMemo(() => {
    const groups = new Map<string, Achievement[]>();
    for (const item of selected?.achievements ?? []) {
      groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
    }
    return [...groups.entries()];
  }, [selected]);

  if (authLoading || loading) return <Spinner />;
  if (!me?.authenticated) return <Navigate to="/" replace />;
  if (!data || !selected) return <Spinner />;

  const total = selected.achievements.length;
  const percent = total ? Math.round((selected.unlocked_count / total) * 100) : 0;

  return (
    <div className="mx-auto min-h-screen max-w-[1180px] px-5 py-6 md:px-8">
      <header className="mb-8 flex flex-wrap items-center gap-3">
        <Link to={`/u/${gid}`} className="btn btn-ghost btn-sm">
          <Icon name="arrow" size={15} className="rotate-180" /> Zur Sammlung
        </Link>
        <div className="ml-auto"><ThemeToggle /></div>
      </header>

      <section className="relative mb-7 overflow-hidden rounded-[28px] border border-amber-300/15 bg-gradient-to-br from-violet-950/70 via-[var(--panel)] to-amber-950/25 p-6 md:p-8">
        <div className="absolute -right-20 -top-24 h-64 w-64 rounded-full bg-amber-300/10 blur-3xl" />
        <div className="relative flex flex-wrap items-center gap-6">
          <Avatar src={selected.avatar} name={selected.username} size={88} className="!rounded-[24px] ring-2 ring-amber-300/30" />
          <div className="min-w-[220px] flex-1">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.24em] text-amber-300">Achievement Hall</div>
            <h1 className="font-display text-3xl font-extrabold md:text-4xl">{selected.username}</h1>
            <p className="mt-2 max-w-xl text-sm text-muted">
              {selected.id === data.user.id
                ? "Dein Weg durch Yamikuns Turm: Sichtbare Ziele zeigen den Pfad, verborgene Prüfungen geben nur einen leisen Hinweis preis. Geheime Erfolge bleiben dabei ganz bei dir."
                : "Hier siehst du nur die öffentlichen Spuren dieses Weges. Geheime Achievements bleiben vollständig privat – auch wenn sie bereits errungen wurden."}
            </p>
          </div>
          <div className="grid h-28 w-28 shrink-0 place-items-center rounded-full p-[7px]" style={{ background: `conic-gradient(#fbbf24 ${percent}%, rgba(255,255,255,.07) 0)` }}>
            <div className="grid h-full w-full place-items-center rounded-full bg-[var(--panel)] text-center">
              <div><div className="font-display text-2xl font-black text-amber-300">{percent}%</div><div className="font-mono text-[9px] uppercase tracking-wider text-faint">{selected.unlocked_count}/{total}</div></div>
            </div>
          </div>
        </div>
      </section>

      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <Icon name="users" size={17} className="text-accent" />
          <h2 className="font-display text-[15px] font-bold">Mit Freunden vergleichen</h2>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {people.map((person) => (
            <button
              key={person.id}
              onClick={() => setSelectedId(person.id)}
              className={`flex min-w-[190px] items-center gap-3 rounded-2xl border p-3 text-left transition-all ${
                person.id === selected.id ? "border-amber-300/35 bg-amber-300/10" : "border-white/[0.07] bg-white/[0.025] hover:border-white/15"
              }`}
            >
              <Avatar src={person.avatar} name={person.username} size={38} />
              <div className="min-w-0">
                <div className="truncate text-[13px] font-bold">{person.username}</div>
                <div className="font-mono text-[10px] text-faint">{person.unlocked_count}/{person.achievements.length} erreicht</div>
              </div>
            </button>
          ))}
        </div>
        {data.friends.length === 0 && (
          <div className="mt-3"><EmptyState icon="users">Füge Freunde mit /friend add hinzu, um eure Achievements hier zu vergleichen.</EmptyState></div>
        )}
      </section>

      <div className="space-y-8">
        {grouped.map(([category, items]) => (
          <section key={category}>
            <div className="mb-3 flex items-center gap-3">
              <h2 className="font-display text-[17px] font-bold">{category}</h2>
              <span className="rounded-full bg-white/[0.05] px-2 py-0.5 font-mono text-[10px] text-faint">
                {items.filter((item) => item.unlocked).length}/{items.length}
              </span>
              <span className="h-px flex-1 bg-white/[0.06]" />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {items.map((item, index) => <AchievementCard key={item.id} item={item} index={index} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
