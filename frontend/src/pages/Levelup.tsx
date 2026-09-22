import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { DiscordMarkdown } from "../components/DiscordMarkdown";
import { maxLen, DISCORD } from "../lib/validators";

type LevelupData = {
  channel_id: string | null;
  message: string;
  ping: boolean;
  channels: { id: string; name: string }[];
  placeholders: string[];
};

const PLACEHOLDER_HELP: Record<string, string> = {
  "{user}": "@Erwähnung",
  "{user_name}": "Anzeigename",
  "{level}": "neues Level",
  "{coins}": "erhaltene Coins",
  "{server}": "Servername",
};

export default function Levelup() {
  const { gid } = useParams();
  const { me } = useAuth();
  const { push } = useToast();
  const { data, loading } = useApiData<LevelupData>(`/api/g/${gid}/levelup`);

  const [channelId, setChannelId] = useState("");
  const [message, setMessage] = useState("");
  const [ping, setPing] = useState(true);
  const [busy, setBusy] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const v = useValidation({ message }, { message: [maxLen(DISCORD.MESSAGE)] });

  useEffect(() => {
    if (data) {
      setChannelId(data.channel_id ?? "");
      setMessage(data.message);
      setPing(data.ping);
    }
  }, [data]);

  if (loading || !data) return <Spinner />;

  const serverName = me?.guilds?.find((g) => g.id === gid)?.name ?? "Dein Server";
  const preview = message
    .replace(/\{user\}/g, "@Mitglied")
    .replace(/\{user_name\}/g, "Mitglied")
    .replace(/\{level\}/g, "5")
    .replace(/\{coins\}/g, "500")
    .replace(/\{server\}/g, serverName);

  function insert(token: string) {
    const ta = taRef.current;
    if (!ta) {
      setMessage((m) => m + token);
      return;
    }
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    setMessage((m) => m.slice(0, start) + token + m.slice(end));
    requestAnimationFrame(() => {
      ta.focus();
      ta.selectionStart = ta.selectionEnd = start + token.length;
    });
  }

  async function save() {
    if (!v.validateAll()) return;
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/levelup`, { channel_id: channelId, message, ping });
      push("ok", "Level-Up-Einstellungen gespeichert.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Level-Up-Nachricht" subtitle="Eigener Aufstiegs-Text & Ping" />
      {!channelId && (
        <InfoBanner>Ohne Channel werden keine Level-Up-Meldungen gepostet.</InfoBanner>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Einstellungen">
          <label className="mb-5 flex flex-col gap-2 label">
            Channel
            <select className="field" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
              <option value="">— kein Channel —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </label>

          <div className="toggle-card mb-5">
            <span>
              <span className="tc-label block">User pingen</span>
              <span className="block text-sm text-muted">
                An = das Mitglied wird benachrichtigt. Aus = stille Meldung.
              </span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={ping} onChange={() => setPing((v) => !v)} />
              <span className="track" />
              <span className="thumb" />
            </label>
          </div>

          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="eyebrow mr-1">Platzhalter</span>
            {data.placeholders.map((p) => (
              <button key={p} type="button" onClick={() => insert(p)} title={PLACEHOLDER_HELP[p]} className="var-chip">
                {p}
              </button>
            ))}
          </div>
          <Field error={v.showError("message")}>
            <textarea
              ref={taRef}
              className="field min-h-[110px] resize-y font-sans"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onBlur={v.blur("message")}
              placeholder="Leer lassen → schönes Standard-Embed mit Level, Belohnung & Kontostand."
            />
          </Field>

          <div className="mt-4 flex items-center justify-between gap-3">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMessage("")}>
              Auf Standard zurücksetzen
            </button>
            <button className="btn-primary" onClick={save} disabled={busy || !v.isValid}>
              {busy ? "Speichere…" : "Speichern"}
            </button>
          </div>
        </Panel>

        <Panel title="Live-Vorschau">
          {message.trim() ? (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="dc-preview">
              <div className="dc-body">
                <div className="dc-text whitespace-pre-wrap"><DiscordMarkdown text={preview} /></div>
              </div>
            </motion.div>
          ) : (
            <div className="rounded-xl border border-border bg-surface-2 p-5 text-sm text-muted">
              <div className="mb-2 font-bold text-txt">🏆 Level 5 erreicht</div>
              <div>Bei leerem Text wird das bisherige Standard-Embed mit Level, Coin-Belohnung
              und Kontostand verschickt.</div>
            </div>
          )}
          <p className="mt-3 text-[0.8rem] text-faint">
            {ping ? "Das Mitglied wird beim Aufstieg gepingt." : "Stille Meldung — kein Ping."}
          </p>
        </Panel>
      </div>
    </>
  );
}
