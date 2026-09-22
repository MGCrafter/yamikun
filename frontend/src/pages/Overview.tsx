import { Link, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useApiData } from "../lib/useApiData";
import type { Overview as OverviewData } from "../lib/api";
import { Icon } from "../components/Icon";
import { AnimatedNumber } from "../components/ui/AnimatedNumber";
import { PageHeader, Panel, Spinner } from "../components/common";

const QUICK = [
  { to: "cards", icon: "layers", label: "Sammelkarten verwalten & hochladen" },
  { to: "yami", icon: "cards", label: "Yami-Karten (Booster) verwalten" },
  { to: "reactionroles", icon: "users", label: "Reaction Roles verwalten" },
  { to: "welcome", icon: "enter", label: "Willkommensnachrichten einstellen" },
  { to: "audit", icon: "scroll", label: "Audit-Log ansehen & konfigurieren" },
  { to: "games", icon: "gamepad", label: "Spiele & Drop-Channel einstellen" },
];

export default function Overview() {
  const { gid } = useParams();
  const { data, loading } = useApiData<OverviewData>(`/api/g/${gid}/overview`);
  if (loading || !data) return <Spinner />;

  const s = data.stats;
  const stats = [
    { n: s.card_types, label: "Kartentypen", icon: "layers" },
    { n: s.games, label: "Belohnungs-Spiele", icon: "gamepad" },
    { n: s.collectors, label: "Sammler", icon: "users" },
    { n: s.total_owned, label: "Karten im Umlauf", icon: "box", fmt: true },
  ];

  return (
    <>
      <PageHeader title="Übersicht" subtitle={data.guild.name} />

      <div className="stat-grid">
        {stats.map((st, i) => (
          <motion.div
            key={st.label}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
            className="stat-card"
          >
            <span className="sc-ic">
              <Icon name={st.icon} size={20} />
            </span>
            <div className="sc-v">
              <AnimatedNumber value={st.n} format={st.fmt} />
            </div>
            <div className="sc-k">{st.label}</div>
          </motion.div>
        ))}
      </div>

      <Panel title="Seltenheits-Verteilung">
        <div className="dist-chips flex flex-wrap gap-2.5">
          {data.rarity_distribution.length === 0 && (
            <span className="text-sm text-faint">Noch keine Karten.</span>
          )}
          {data.rarity_distribution.map((r) => (
            <span key={r.key} className="chip">
              <span className="dot" style={{ background: r.color }} />
              {r.label} <b>{r.count}</b>
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Schnellzugriff">
        <div className="quick-list">
          {QUICK.map((q) => (
            <Link key={q.to} to={`/g/${gid}/${q.to}`} className="quick-row">
              <span className="qi">
                <Icon name={q.icon} size={20} />
              </span>
              {q.label}
              <span className="arr">
                <Icon name="arrow" size={18} />
              </span>
            </Link>
          ))}
        </div>
        <div className="mt-4 text-[13px] text-faint">
          Drop-Channel aktuell: <b className="text-txt">{s.channel_label}</b>
        </div>
      </Panel>
    </>
  );
}
