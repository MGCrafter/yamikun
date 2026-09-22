import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, EmptyState, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, maxLen, DISCORD } from "../lib/validators";

type Category = { id: number; label: string; emoji: string | null; description: string | null };
type TicketRow = {
  number: number;
  category: string;
  opener: string;
  claimed_by: string | null;
  status: string;
  created_at: number;
  thread_link: string;
};
type TranscriptRow = {
  token: string;
  number: number;
  category: string;
  opener: string;
  closed_by: string;
  closed_at: number;
  messages: number;
  url: string;
};
type TicketsData = {
  enabled: boolean;
  panel_channel_id: string | null;
  panel_channel_name: string | null;
  support_role_id: string | null;
  log_channel_id: string | null;
  title: string;
  text: string;
  default_title: string;
  default_text: string;
  categories: Category[];
  open_count: number;
  tickets: TicketRow[];
  transcripts: TranscriptRow[];
  roles: { id: string; name: string; color: string | null; assignable: boolean }[];
  channels: { id: string; name: string }[];
};

const fmtDate = (s: number) =>
  new Date(s * 1000).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function Tickets() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<TicketsData>(`/api/g/${gid}/tickets`);

  const [supportRole, setSupportRole] = useState("");
  const [logChannel, setLogChannel] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [panelChannel, setPanelChannel] = useState("");
  const [busy, setBusy] = useState(false);
  const [panelBusy, setPanelBusy] = useState(false);

  // Neue Kategorie
  const [catLabel, setCatLabel] = useState("");
  const [catEmoji, setCatEmoji] = useState("");
  const [catDesc, setCatDesc] = useState("");
  const [catBusy, setCatBusy] = useState(false);

  const pv = useValidation(
    { channel_id: panelChannel },
    { channel_id: [required("Bitte einen Channel fürs Panel wählen.")] },
  );
  const cfgv = useValidation(
    { title, text },
    { title: [maxLen(DISCORD.EMBED_TITLE)], text: [maxLen(DISCORD.EMBED_DESC)] },
  );
  const catv = useValidation(
    { label: catLabel },
    { label: [required("Bitte einen Namen für das Thema angeben."), maxLen(100)] },
  );

  useEffect(() => {
    if (data) {
      setSupportRole(data.support_role_id ?? "");
      setLogChannel(data.log_channel_id ?? "");
      setTitle(data.title);
      setText(data.text);
      setPanelChannel(data.panel_channel_id ?? "");
    }
  }, [data]);

  if (loading || !data) return <Spinner />;

  async function saveConfig() {
    if (!cfgv.validateAll()) return;
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/tickets/config`, {
        support_role_id: supportRole,
        log_channel_id: logChannel,
        title,
        text,
      });
      push("ok", "Einstellungen gespeichert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function postPanel() {
    if (!pv.validateAll()) return;
    setPanelBusy(true);
    try {
      await api.post(`/api/g/${gid}/tickets/panel`, { channel_id: panelChannel });
      push("ok", "Ticket-Panel gepostet — das System ist aktiv.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setPanelBusy(false);
    }
  }

  async function disable() {
    if (!confirm("Ticket-System deaktivieren und das Panel entfernen?")) return;
    setPanelBusy(true);
    try {
      await api.post(`/api/g/${gid}/tickets/disable`, {});
      push("ok", "Ticket-System deaktiviert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setPanelBusy(false);
    }
  }

  async function addCategory() {
    if (!catv.validateAll()) return;
    setCatBusy(true);
    try {
      await api.post(`/api/g/${gid}/tickets/category/add`, {
        label: catLabel,
        emoji: catEmoji,
        description: catDesc,
      });
      setCatLabel("");
      setCatEmoji("");
      setCatDesc("");
      catv.reset();
      push("ok", "Thema hinzugefügt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setCatBusy(false);
    }
  }

  async function removeCategory(c: Category) {
    if (!confirm(`Thema „${c.label}" entfernen?`)) return;
    try {
      await api.post(`/api/g/${gid}/tickets/category/remove`, { id: c.id });
      push("ok", "Thema entfernt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  return (
    <>
      <PageHeader
        title="Ticket-System"
        subtitle={data.enabled ? `🟢 Aktiv · ${data.open_count} offene Tickets` : "🔴 Deaktiviert"}
      />

      {data.enabled && !data.support_role_id && (
        <InfoBanner>
          Es ist noch keine Support-Rolle gesetzt — sie wird bei neuen Tickets gepingt. Trag sie unten ein.
        </InfoBanner>
      )}

      {/* Panel posten / Status */}
      <Panel title="Panel & Status">
        <p className="mb-4 text-sm text-muted">
          Das Panel ist die Nachricht mit dem Auswahlmenü, über das Mitglieder Tickets öffnen. Wähle einen
          Channel und poste es — damit wird das System aktiviert. Erneutes Posten ersetzt das alte Panel.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <Field label="Panel-Channel" required error={pv.showError("channel_id")} className="flex-1">
            <select
              className="field"
              value={panelChannel}
              onChange={(e) => setPanelChannel(e.target.value)}
              onBlur={pv.blur("channel_id")}
            >
              <option value="">— Channel wählen —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </Field>
          <button className="btn-primary" onClick={postPanel} disabled={panelBusy || !pv.isValid}>
            <Icon name="ticket" size={16} /> {data.enabled ? "Panel erneuern" : "Panel posten"}
          </button>
        </div>
        {data.enabled && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3">
            <span className="text-sm text-muted">
              Panel läuft in <b>#{data.panel_channel_name ?? "?"}</b>.
            </span>
            <button className="btn btn-ghost btn-sm text-danger" onClick={disable} disabled={panelBusy}>
              <Icon name="x" size={15} /> Deaktivieren
            </button>
          </div>
        )}
      </Panel>

      {/* Alle Tickets */}
      <Panel title={`Alle Tickets (${data.tickets.length})`}>
        {data.tickets.length === 0 ? (
          <EmptyState icon="ticket">Noch keine Tickets erstellt.</EmptyState>
        ) : (
          <div className="list">
            {data.tickets.map((t) => (
              <div
                key={t.number}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 transition-colors hover:border-border-strong"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    className={`flex-none rounded-full px-2 py-0.5 text-[0.7rem] font-bold ${
                      t.status === "open"
                        ? "bg-[var(--r-uncommon)]/20 text-[var(--r-uncommon)]"
                        : "bg-surface-3 text-faint"
                    }`}
                  >
                    {t.status === "open" ? "OFFEN" : "ZU"}
                  </span>
                  <span className="font-semibold">#{String(t.number).padStart(4, "0")}</span>
                  <span className="truncate text-sm text-muted">
                    {t.category} · {t.opener}
                    {t.claimed_by && <> · 🙋 {t.claimed_by}</>}
                  </span>
                </div>
                <a
                  href={t.thread_link}
                  target="_blank"
                  rel="noreferrer"
                  className="hidden flex-none text-[0.8rem] text-faint hover:text-accent sm:inline"
                >
                  Thread öffnen ↗
                </a>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Transcripts */}
      <Panel title={`Transcripts (${data.transcripts.length})`}>
        <p className="mb-4 text-sm text-muted">
          Geschlossene Tickets als hübscher Web-Verlauf. Der Link funktioniert auch ohne Login —
          teile ihn nur mit Leuten, die den Verlauf sehen dürfen.
        </p>
        {data.transcripts.length === 0 ? (
          <EmptyState icon="scroll">Noch keine geschlossenen Tickets.</EmptyState>
        ) : (
          <div className="list">
            {data.transcripts.map((t) => (
              <a
                key={t.token}
                href={t.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 transition-colors hover:border-accent/50"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Icon name="scroll" size={16} className="flex-none text-faint" />
                  <span className="font-semibold">#{String(t.number).padStart(4, "0")}</span>
                  <span className="truncate text-sm text-muted">
                    {t.category} · {t.opener} · {t.messages} Nachr. · {fmtDate(t.closed_at)}
                  </span>
                </div>
                <span className="hidden flex-none text-[0.8rem] text-accent sm:inline">Ansehen →</span>
              </a>
            ))}
          </div>
        )}
      </Panel>

      {/* Einstellungen */}
      <Panel title="Einstellungen">
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="flex flex-col gap-2 label">
            Support-Rolle (wird gepingt)
            <select className="field" value={supportRole} onChange={(e) => setSupportRole(e.target.value)}>
              <option value="">— keine —</option>
              {data.roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-2 label">
            Log-Channel (Transcripts)
            <select className="field" value={logChannel} onChange={(e) => setLogChannel(e.target.value)}>
              <option value="">— kein Logging —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <Field label="Panel-Titel" error={cfgv.showError("title")} className="mt-5">
          <input
            className="field"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={cfgv.blur("title")}
            placeholder={data.default_title}
          />
        </Field>
        <Field label="Panel-Text" error={cfgv.showError("text")} className="mt-4">
          <textarea
            className="field min-h-[90px] resize-y font-sans"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={cfgv.blur("text")}
            placeholder={data.default_text}
          />
        </Field>

        <div className="mt-5 flex justify-end">
          <button className="btn-primary" onClick={saveConfig} disabled={busy || !cfgv.isValid}>
            {busy ? "Speichere…" : "Speichern"}
          </button>
        </div>
      </Panel>

      {/* Themen */}
      <Panel title="Themen (Panel-Optionen)">
        <p className="mb-4 text-sm text-muted">
          Jedes Thema ist eine Option im Auswahlmenü. Ohne Themen wird ein einzelnes Standard-Thema
          „Support" angeboten.
        </p>

        {data.categories.length === 0 ? (
          <EmptyState icon="ticket">Noch keine Themen — es gilt das Standard-Thema „Support".</EmptyState>
        ) : (
          <div className="list mb-5">
            {data.categories.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 transition-colors hover:border-border-strong"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="text-lg leading-none">{c.emoji || "🎫"}</span>
                  <span className="font-semibold">{c.label}</span>
                  {c.description && (
                    <span className="hidden truncate text-[0.82rem] text-faint sm:inline">— {c.description}</span>
                  )}
                </div>
                <button
                  onClick={() => removeCategory(c)}
                  title="Entfernen"
                  className="grid h-8 w-8 flex-none place-items-center rounded-lg text-faint transition hover:bg-danger/10 hover:text-danger"
                >
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="eyebrow mb-2">Thema hinzufügen</div>
        <div className="grid gap-3 sm:grid-cols-[80px_1fr]">
          <Field label="Emoji">
            <input
              className="field"
              value={catEmoji}
              onChange={(e) => setCatEmoji(e.target.value)}
              placeholder="🎫"
              maxLength={32}
            />
          </Field>
          <Field label="Thema-Name" required error={catv.showError("label")}>
            <input
              className="field"
              value={catLabel}
              onChange={(e) => setCatLabel(e.target.value)}
              onBlur={catv.blur("label")}
              placeholder="Name (z.B. Support, Bewerbung, Report)"
              maxLength={100}
            />
          </Field>
        </div>
        <Field label="Beschreibung (optional)" className="mt-3">
          <input
            className="field"
            value={catDesc}
            onChange={(e) => setCatDesc(e.target.value)}
            placeholder="Optionaler Hinweistext unter dem Thema"
            maxLength={100}
          />
        </Field>
        <div className="mt-4 flex justify-end">
          <button className="btn-ghost" onClick={addCategory} disabled={catBusy || !catv.isValid}>
            <Icon name="plus" size={16} /> Thema hinzufügen
          </button>
        </div>
      </Panel>
    </>
  );
}
