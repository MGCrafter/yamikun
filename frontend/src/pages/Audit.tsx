import { useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { PageHeader, Panel, EmptyState, Spinner } from "../components/common";

type Entry = {
  id: number;
  ts: number;
  category: string;
  event_type: string;
  summary: string;
  detail: string | null;
  actor: string | null;
  target: string | null;
  channel_name: string | null;
};
type Setting = { key: string; label: string; enabled: boolean };
type AuditData = {
  entries: Entry[];
  settings: Setting[];
  channel_id: string | null;
  channels: { id: string; name: string }[];
};

const CAT_COLOR: Record<string, string> = {
  messages: "#5865F2",
  voice: "#2ECC71",
  members: "#3498DB",
  roles: "#F1C40F",
  channels: "#9B59B6",
};

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Audit() {
  const { gid } = useParams();
  const { push } = useToast();
  const [filter, setFilter] = useState("");
  const q = filter ? `?category=${filter}` : "";
  const { data, loading, reload } = useApiData<AuditData>(`/api/g/${gid}/audit${q}`);

  if (loading || !data) return <Spinner />;

  async function toggle(s: Setting) {
    try {
      await api.post(`/api/g/${gid}/audit/settings`, { category: s.key, enabled: !s.enabled });
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function setChannel(channelId: string) {
    try {
      await api.post(`/api/g/${gid}/audit/channel`, { channel_id: channelId });
      push("ok", "Audit-Channel gespeichert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function clearLog() {
    if (!confirm("Wirklich das gesamte Audit-Log dieses Servers löschen?")) return;
    try {
      await api.post(`/api/g/${gid}/audit/clear`, {});
      push("ok", "Audit-Log geleert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  return (
    <>
      <PageHeader title="Audit-Log" subtitle="Server-Ereignisse protokollieren" />

      <Panel title="Was wird protokolliert?">
        <div className="grid gap-2.5 sm:grid-cols-2">
          {data.settings.map((s) => (
            <div key={s.key} className="toggle-card">
              <span className="tc-dot" style={{ background: CAT_COLOR[s.key] }} />
              <span className="tc-label">{s.label}</span>
              <label className="switch">
                <input type="checkbox" checked={s.enabled} onChange={() => toggle(s)} />
                <span className="track" />
                <span className="thumb" />
              </label>
            </div>
          ))}
        </div>
        <label className="mt-5 flex flex-col gap-2 label">
          Live-Channel (optional — postet Ereignisse zusätzlich in Discord)
          <select className="field" value={data.channel_id ?? ""} onChange={(e) => setChannel(e.target.value)}>
            <option value="">— kein Channel —</option>
            {data.channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
        </label>
      </Panel>

      <Panel title={`Verlauf (${data.entries.length})`}>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <button className="filter-pill" data-on={filter === ""} onClick={() => setFilter("")}>
            Alle
          </button>
          {data.settings.map((s) => (
            <button key={s.key} className="filter-pill" data-on={filter === s.key} onClick={() => setFilter(s.key)}>
              {s.label}
            </button>
          ))}
          <button onClick={clearLog} className="btn btn-ghost btn-sm ml-auto hover:text-danger">
            Log leeren
          </button>
        </div>

        {data.entries.length === 0 ? (
          <EmptyState>Noch keine Einträge — sobald etwas passiert, erscheint es hier.</EmptyState>
        ) : (
          <div className="log-list">
            {data.entries.map((e) => (
              <div key={e.id} className="log-row">
                <span className="ldot" style={{ background: CAT_COLOR[e.category] ?? "#888" }} />
                <div className="ltxt">
                  <div>{e.summary}</div>
                  {e.detail && (
                    <div className="mt-1 whitespace-pre-wrap rounded-md bg-inset px-2 py-1 text-[0.8rem] text-muted">
                      {e.detail}
                    </div>
                  )}
                </div>
                <span className="ltime">{fmtTime(e.ts)}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
