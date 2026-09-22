import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useApiData } from "../lib/useApiData";
import { api, errText, type Card } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";
import { CardTile } from "../components/ui/CardTile";
import { CardAlbum, type AlbumGame } from "../components/ui/CardAlbum";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/Icon";
import { fmtNum } from "../lib/utils";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Panel, Spinner } from "../components/common";

type GameGroup = AlbumGame;
type DashData = {
  guild: { id: string; name: string };
  username: string;
  avatar: string | null;
  is_admin: boolean;
  stats: { level: number; xp_into: number; xp_needed: number; total_xp: number; coins: number };
  games: GameGroup[];
  card_album: { shards: number; booster_cost: number; dismantle_rewards: Record<string, number> };
  yami: { cards: Card[]; fusable: Record<string, number> };
  fusable_rarities: string[];
};

export default function UserDashboard() {
  const { gid } = useParams();
  const { me, loading: meLoading } = useAuth();
  const navigate = useNavigate();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<DashData>(`/api/u/${gid}/dashboard`);
  const [busy, setBusy] = useState<string | null>(null);

  if (meLoading || loading) return <Spinner />;
  if (!me?.authenticated) return <Navigate to="/" replace />;
  const memberGuilds = me.member_guilds ?? [];
  if (!data) return <Spinner />;

  const rarMeta = Object.fromEntries((me.rarities ?? []).map((r) => [r.key, r]));

  async function fuse(kind: "game" | "yami", rarity: string, game?: string) {
    const key = `${kind}:${game ?? ""}:${rarity}`;
    setBusy(key);
    try {
      const r = await api.post(`/api/u/${gid}/fuse`, { kind, rarity, game });
      push("ok", `Fusion erfolgreich — ${r.result.rarity_label} „${r.result.name}" erhalten.`);
      reload();
    } catch (e) {
      push("err", errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function dismantle(card: Card): Promise<boolean> {
    const key = `dismantle:${card.id}`;
    setBusy(key);
    try {
      const result = await api.post(`/api/u/${gid}/cards/dismantle`, { card_id: card.id });
      push("ok", `„${card.name}“ zerlegt — +${result.reward} Arkansplitter.`);
      await reload();
      return true;
    } catch (e) {
      push("err", errText(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function exchangeBooster(game: GameGroup): Promise<boolean> {
    const key = `exchange:${game.game}`;
    setBusy(key);
    try {
      await api.post(`/api/u/${gid}/boosters/exchange`, { game: game.game });
      push("ok", `${game.game}-Booster eingetauscht und ins Inventar gelegt.`);
      await reload();
      return true;
    } catch (e) {
      push("err", errText(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  const FuseButtons = ({ kind, game, fusable }: { kind: "game" | "yami"; game?: string; fusable: Record<string, number> }) => {
    const avail = data.fusable_rarities.filter((r) => (fusable[r] ?? 0) > 0);
    if (avail.length === 0) return <span className="text-[0.82rem] text-faint">Nichts zum Fusionieren.</span>;
    return (
      <div className="flex flex-wrap gap-2">
        {avail.map((r) => {
          const count = fusable[r] ?? 0;
          const ready = count >= 5;
          const meta = rarMeta[r];
          const k = `${kind}:${game ?? ""}:${r}`;
          return (
            <button
              key={r}
              disabled={!ready || busy === k}
              onClick={() => fuse(kind, r, game)}
              title={ready ? "5 → 1 der nächsten Seltenheit" : "Mindestens 5 nötig"}
              className="chip relative overflow-hidden !py-2 transition-colors disabled:cursor-not-allowed"
              style={{
                borderColor: ready ? `color-mix(in oklab, ${meta?.color} 55%, transparent)` : undefined,
                color: ready ? "var(--text)" : "var(--faint)",
              }}
            >
              <span className="dot" style={{ background: meta?.color }} />
              {meta?.label ?? r}
              <span className="font-mono text-faint">{count}/5</span>
              {ready && <Icon name="arrow" size={13} className="text-accent" />}
              <span
                className="absolute bottom-0 left-0 h-[2px] transition-all"
                style={{ width: `${Math.min(100, (count / 5) * 100)}%`, background: meta?.color }}
              />
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div className="mx-auto min-h-screen max-w-[1380px] px-5 py-6 md:px-8">
      {/* Header */}
      <header className="mb-7 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-3 font-display text-[19px] font-bold">
          <img src="/assets/YamiKun.webp" alt="" className="h-8 w-8 rounded-full object-cover" />
          <span>Yamikun</span>
        </div>
        <div className="ml-auto flex items-center gap-2.5">
          {memberGuilds.length > 1 && (
            <select
              value={gid}
              onChange={(e) => navigate(`/u/${e.target.value}`)}
              className="field cursor-pointer py-2 font-semibold"
            >
              {memberGuilds.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          )}
          {data.is_admin && (
            <Link to={`/g/${gid}/overview`} className="btn btn-ghost btn-sm">
              <Icon name="arrow" size={15} className="rotate-180" /> Admin-Panel
            </Link>
          )}
          <Link to={`/u/${gid}/achievements`} className="btn btn-ghost btn-sm">
            🏆 Achievements
          </Link>
          <Link to={`/u/${gid}/support`} className="btn btn-ghost btn-sm">
            <Icon name="alert" size={15} /> Support
          </Link>
          <a href="/logout" className="inline-flex items-center gap-2 px-2 py-2 text-[13px] text-faint hover:text-danger">
            <Icon name="logout" size={16} /> Abmelden
          </a>
          <ThemeToggle />
        </div>
      </header>

      {/* Profil / Stats */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="panel hero mb-6 flex-wrap">
        <div className="ava-wrap">
          <span className="ava-ring" />
          <Avatar src={data.avatar} name={data.username} size={84} online className="!rounded-[22px]" />
        </div>
        <div className="min-w-[180px] flex-1">
          <div className="h-name">{data.username}</div>
          <div className="h-title">{data.guild.name}</div>
          <div className="xp">
            <div className="xp-track">
              <div
                className="xp-fill"
                style={{ width: `${Math.min(100, (data.stats.xp_into / Math.max(1, data.stats.xp_needed)) * 100)}%` }}
              />
            </div>
            <div className="xp-label mt-1.5">
              {fmtNum(data.stats.xp_into)} / {fmtNum(data.stats.xp_needed)} XP
            </div>
          </div>
        </div>
        <div className="flex gap-3">
          <div className="stat">
            <div className="v">{data.stats.level}</div>
            <div className="k">Level</div>
          </div>
          <div className="stat">
            <div className="v coins">{fmtNum(data.stats.coins)}</div>
            <div className="k">Coins</div>
          </div>
        </div>
      </motion.div>

      {/* Fusion */}
      <Panel
        title={(
          <span className="inline-flex items-center gap-2">
            <Icon name="fusion" size={19} className="text-accent" />
            Fusion — 5 Karten → 1 der nächsten Seltenheit (bis Legendary)
          </span>
        )}
      >
        <div className="flex flex-col gap-4">
          {data.games.map((g) => (
            <div key={g.game}>
              <div className="mb-2 font-mono text-[12px] tracking-wide text-muted">{g.game}</div>
              <FuseButtons kind="game" game={g.game === "Ohne Spiel" ? "" : g.game} fusable={g.fusable} />
            </div>
          ))}
          {data.yami.cards.length > 0 && (
            <div>
              <div className="mb-2 font-mono text-[12px] tracking-wide text-muted">Yami-Karten</div>
              <FuseButtons kind="yami" fusable={data.yami.fusable} />
            </div>
          )}
          {data.games.length === 0 && data.yami.cards.length === 0 && (
            <span className="text-[0.85rem] text-faint">Noch keine Karten zum Fusionieren.</span>
          )}
        </div>
      </Panel>

      {/* Spiel-Sammelalbum – ersetzt die frühere Kartenraster-Ansicht im Profil. */}
      <CardAlbum
        games={data.games}
        shards={data.card_album.shards}
        boosterCost={data.card_album.booster_cost}
        dismantleRewards={data.card_album.dismantle_rewards}
        busy={busy}
        onDismantle={dismantle}
        onExchange={exchangeBooster}
      />

      {/* Yami-Karten bleiben ein getrenntes System und werden nicht vermischt. */}
      {data.yami.cards.length > 0 && (
        <Panel
          title={(
            <span className="inline-flex items-center gap-2">
              <Icon name="sparkle" size={19} className="text-accent" />
              Yami-Karten
            </span>
          )}
        >
          <div className="card-grid">
            {data.yami.cards.map((card, index) => <CardTile key={card.id} card={card} index={index} />)}
          </div>
        </Panel>
      )}
    </div>
  );
}
