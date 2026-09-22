import { useAuth } from "../lib/auth";
import { useParams, useSearchParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText, type Card, type Collector, type InventoryUser } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { CardTile } from "../components/ui/CardTile";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, EmptyState, Spinner } from "../components/common";

export default function Inventory() {
  const { gid } = useParams();
  const [params, setParams] = useSearchParams();
  const userId = params.get("user");

  if (userId) return <UserDetail gid={gid!} uid={userId} onBack={() => setParams({})} />;
  return <CollectorList gid={gid!} onOpen={(uid) => setParams({ user: uid })} />;
}

function CollectorList({ gid, onOpen }: { gid: string; onOpen: (uid: string) => void }) {
  const { data, loading } = useApiData<{ collectors: Collector[] }>(`/api/g/${gid}/inventory`);
  if (loading || !data) return <Spinner />;

  return (
    <>
      <PageHeader title="Inventare" subtitle={`${data.collectors.length} Sammler`} />
      <Panel title="Sammler">
        {data.collectors.length === 0 ? (
          <EmptyState>Noch niemand besitzt Karten.</EmptyState>
        ) : (
          <div className="list">
            {data.collectors.map((c) => (
              <button key={c.user_id} onClick={() => onOpen(c.user_id)} className="list-row">
                <Avatar src={c.avatar} name={c.name} size={38} />
                <span className="lr-name">{c.name}</span>
                <span className="lr-meta">
                  {c.game_count} Sammel · {c.yami_count} Yami
                </span>
                <Icon name="arrow" size={18} className="text-faint" />
              </button>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}

function UserDetail({ gid, uid, onBack }: { gid: string; uid: string; onBack: () => void }) {
  const { push } = useToast();
  const { me } = useAuth();
  const { data, loading, reload } = useApiData<InventoryUser>(`/api/g/${gid}/inventory/user/${uid}`);
  if (loading || !data) return <Spinner />;

  async function remove(card: Card, kind: "game" | "yami") {
    if (!confirm(`„${card.name}“ komplett aus dem Inventar entfernen?`)) return;
    try {
      await api.post(`/api/g/${gid}/inventory/remove`, { user_id: uid, card_id: card.id, kind });
      push("ok", "Karte entfernt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  const Grid = ({ cards, kind }: { cards: Card[]; kind: "game" | "yami" }) =>
    cards.length === 0 ? (
      <EmptyState>{kind === "yami" ? "Keine Yami-Karten." : "Keine Sammelkarten."}</EmptyState>
    ) : (
      <div className="card-grid">
        {cards.map((c, i) => (
          <CardTile key={c.id} card={c} index={i} onDelete={me?.can_manage_global_assets ? (card) => remove(card, kind) : undefined} />
        ))}
      </div>
    );

  return (
    <>
      <button onClick={onBack} className="btn btn-ghost btn-sm mb-5">
        <Icon name="arrow" size={16} className="rotate-180" /> Alle Sammler
      </button>
      <div className="mb-6 flex items-center gap-4">
        <Avatar src={data.avatar} name={data.name} size={56} />
        <div>
          <h1 className="font-display text-[1.7rem] font-bold tracking-tight">{data.name}</h1>
          <div className="text-[0.9rem] text-muted">Inventar</div>
        </div>
      </div>
      <Panel title="🎴 Sammelkarten">
        <Grid cards={data.game_cards} kind="game" />
      </Panel>
      <Panel title="✨ Yami-Karten">
        <Grid cards={data.yami_cards} kind="yami" />
      </Panel>
    </>
  );
}
