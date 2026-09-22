import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Field } from "../components/ui/Field";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";
import { useValidation } from "../lib/useValidation";
import { maxLen, required, DISCORD } from "../lib/validators";

type TwitchData = {
  enabled: boolean;
  login: string;
  channel_id: string | null;
  message: string;
  mention_role_id: string | null;
  channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  placeholders: string[];
  credentials_configured: boolean;
};

const HELP: Record<string, string> = {
  "{streamer}": "Twitch-Anzeigename",
  "{title}": "Streamtitel",
  "{game}": "Kategorie / Spiel",
  "{url}": "Twitch-Link",
};

export default function Twitch() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading } = useApiData<TwitchData>(`/api/g/${gid}/twitch`);
  const [enabled, setEnabled] = useState(false);
  const [login, setLogin] = useState("");
  const [channelId, setChannelId] = useState("");
  const [message, setMessage] = useState("");
  const [mentionRoleId, setMentionRoleId] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const v = useValidation(
    { login, channelId, message },
    {
      login: enabled ? [required("Bitte Twitch-Link oder Twitch-Namen eingeben.")] : [],
      channelId: enabled ? [required("Bitte einen Discord-Channel wählen.")] : [],
      message: [maxLen(DISCORD.MESSAGE)],
    },
  );

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setLogin(data.login);
    setChannelId(data.channel_id ?? "");
    setMessage(data.message);
    setMentionRoleId(data.mention_role_id ?? "");
  }, [data]);

  if (loading || !data) return <Spinner />;

  function insert(token: string) {
    const textarea = ref.current;
    if (!textarea) return setMessage((current) => current + token);
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    setMessage((current) => current.slice(0, start) + token + current.slice(end));
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.selectionStart = textarea.selectionEnd = start + token.length;
    });
  }

  async function save() {
    if (!v.validateAll()) return;
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/twitch`, {
        enabled,
        login,
        channel_id: channelId,
        message,
        mention_role_id: mentionRoleId,
      });
      push("ok", "Twitch-Live-Benachrichtigung gespeichert.");
    } catch (error) {
      push("err", errText(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Twitch Live" subtitle="Postet automatisch, sobald ein Twitch-Kanal live geht" />
      {!data.credentials_configured && (
        <InfoBanner>
          Twitch ist noch nicht mit dem Bot verbunden. In CapRover müssen zuerst TWITCH_CLIENT_ID und
          TWITCH_CLIENT_SECRET hinterlegt werden; die Werte werden niemals im WebPanel gespeichert.
        </InfoBanner>
      )}
      {enabled && (!login || !channelId) && (
        <InfoBanner>Bitte Twitch-Kanal und Ziel-Channel wählen — erst dann kann Yami posten.</InfoBanner>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Live-Benachrichtigung">
          <div className="toggle-card mb-5">
            <span>
              <span className="tc-label block">Aktiviert</span>
              <span className="block text-sm text-muted">Yami prüft den Twitch-Kanal etwa jede Minute.</span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={enabled} onChange={() => setEnabled((value) => !value)} />
              <span className="track" /><span className="thumb" />
            </label>
          </div>
          <Field label="Twitch-Kanal oder Link" required={enabled} error={v.showError("login")} className="mb-5"
            hint="Ein Link wird automatisch zum Kanalnamen gekürzt — das ist richtig so, Twitch kennt nur den Namen.">
            <input className="field" value={login} onChange={(e) => setLogin(e.target.value)} onBlur={v.blur("login")}
              placeholder="z. B. https://twitch.tv/streamername" />
          </Field>
          <Field label="Discord-Ziel-Channel" required={enabled} error={v.showError("channelId")} className="mb-5">
            <select className="field" value={channelId} onChange={(e) => setChannelId(e.target.value)} onBlur={v.blur("channelId")}>
              <option value="">— kein Channel —</option>
              {data.channels.map((channel) => <option key={channel.id} value={channel.id}>#{channel.name}</option>)}
            </select>
          </Field>
          <Field label="Rolle beim Livegang erwähnen (optional)" className="mb-5">
            <select className="field" value={mentionRoleId} onChange={(e) => setMentionRoleId(e.target.value)}>
              <option value="">— keine Rolle pingen —</option>
              {data.roles.map((role) => <option key={role.id} value={role.id}>@{role.name}</option>)}
            </select>
          </Field>
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="eyebrow mr-1">Platzhalter</span>
            {data.placeholders.map((token) => <button key={token} type="button" className="var-chip" title={HELP[token]} onClick={() => insert(token)}>{token}</button>)}
          </div>
          <Field label="Nachricht" error={v.showError("message")}>
            <textarea ref={ref} className="field min-h-[130px] resize-y font-sans" value={message}
              onChange={(e) => setMessage(e.target.value)} onBlur={v.blur("message")} />
          </Field>
          <button className="btn btn-primary mt-5" type="button" onClick={save} disabled={busy}>
            {busy ? "Speichert…" : "Twitch-Einstellungen speichern"}
          </button>
        </Panel>
        <Panel title="So funktioniert es">
          <div className="space-y-4 text-sm text-muted">
            <p>Bei jedem neuen Live-Stream erscheint ein Discord-Embed mit Streamtitel, Kategorie, Vorschaubild und direktem Twitch-Link.</p>
            <p>Jede Stream-ID wird nur einmal gepostet. Nach dem Offlinegehen wird der nächste Livegang wieder erkannt.</p>
            <p className="rounded-sm border border-border bg-surface-2 p-3">Für die automatische Abonnenten-Zuordnung braucht jede Person zusätzlich eine sichere Twitch-zu-Discord-Verknüpfung. Das ist ein eigenes Feature, da Twitch-Abos nicht automatisch einer Discord-ID zugeordnet werden können.</p>
          </div>
        </Panel>
      </div>
    </>
  );
}
