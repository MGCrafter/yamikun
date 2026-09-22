import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";
import { ImageDropzone } from "../components/ui/ImageDropzone";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { DiscordMarkdown } from "../components/DiscordMarkdown";
import { required, maxLen, httpUrl, DISCORD } from "../lib/validators";

type BoostData = {
  enabled: boolean;
  channel_id: string | null;
  message: string;
  mention: boolean;
  image: string | null;
  default_message: string;
  channels: { id: string; name: string }[];
  placeholders: string[];
};

const PLACEHOLDER_HELP: Record<string, string> = {
  "{user}": "@Erwähnung",
  "{username}": "Discord-Name",
  "{displayName}": "Anzeigename",
  "{server}": "Servername",
  "{boostCount}": "Boost-Anzahl",
};

export default function Boost() {
  const { gid } = useParams();
  const { me } = useAuth();
  const { push } = useToast();
  const { data, loading } = useApiData<BoostData>(`/api/g/${gid}/boost`);

  const [enabled, setEnabled] = useState(false);
  const [mention, setMention] = useState(true);
  const [channelId, setChannelId] = useState("");
  const [message, setMessage] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [urlInput, setUrlInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [imgBusy, setImgBusy] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Channel ist nur Pflicht, wenn das System aktiviert ist.
  const v = useValidation(
    { channel_id: channelId, message },
    {
      channel_id: enabled ? [required("Bitte einen Channel wählen, wenn aktiviert.")] : [],
      message: [maxLen(DISCORD.MESSAGE)],
    },
  );
  const uv = useValidation(
    { url: urlInput },
    { url: [required("Bitte eine Bild-URL angeben."), httpUrl()] },
  );

  useEffect(() => {
    if (data) {
      setEnabled(data.enabled);
      setMention(data.mention);
      setChannelId(data.channel_id ?? "");
      setMessage(data.message);
      setImage(data.image);
    }
  }, [data]);

  if (loading || !data) return <Spinner />;

  const serverName = me?.guilds?.find((g) => g.id === gid)?.name ?? "Dein Server";
  const preview = message
    .replace(/\{user\}/g, "@Booster")
    .replace(/\{username\}/g, "Booster")
    .replace(/\{displayName\}/g, "Booster")
    .replace(/\{server\}/g, serverName)
    .replace(/\{boostCount\}/g, "7");

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
      await api.post(`/api/g/${gid}/boost`, { enabled, channel_id: channelId, message, mention });
      push("ok", "Boost-Nachricht gespeichert.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function uploadImage(file: File) {
    const form = new FormData();
    form.append("image", file);
    setImgBusy(true);
    try {
      const r = await api.upload(`/api/g/${gid}/boost/upload`, form);
      setImage(r.url);
      push("ok", "Banner hochgeladen.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setImgBusy(false);
    }
  }

  async function applyUrl() {
    if (!uv.validateAll()) return;
    const u = urlInput.trim();
    setImgBusy(true);
    try {
      await api.post(`/api/g/${gid}/boost/image`, { url: u });
      setImage(u);
      setUrlInput("");
      push("ok", "Bild über URL gesetzt.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setImgBusy(false);
    }
  }

  async function removeImage() {
    setImgBusy(true);
    try {
      await api.post(`/api/g/${gid}/boost/image`, { url: "" });
      setImage(null);
      push("ok", "Banner entfernt.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setImgBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Boost-Nachricht" subtitle="Mitglieder fürs Boosten des Servers feiern" />
      {enabled && !channelId && (
        <InfoBanner>Bitte einen Channel wählen — sonst wird nichts gepostet.</InfoBanner>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Einstellungen */}
        <Panel title="Einstellungen">
          <div className="toggle-card mb-5">
            <span>
              <span className="tc-label block">Aktiviert</span>
              <span className="block text-sm text-muted">Boost-Nachricht im gewählten Channel posten.</span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={enabled} onChange={() => setEnabled((v) => !v)} />
              <span className="track" />
              <span className="thumb" />
            </label>
          </div>

          <div className="toggle-card mb-5">
            <span>
              <span className="tc-label block">Booster erwähnen</span>
              <span className="block text-sm text-muted">Das Mitglied in der Nachricht direkt pingern.</span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={mention} onChange={() => setMention((v) => !v)} />
              <span className="track" />
              <span className="thumb" />
            </label>
          </div>

          <Field label="Channel" required={enabled} error={v.showError("channel_id")} className="mb-5">
            <select
              className="field"
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              onBlur={v.blur("channel_id")}
            >
              <option value="">— kein Channel —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </Field>

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
              placeholder={data.default_message}
            />
          </Field>

          <div className="mt-4 flex items-center justify-between gap-3">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMessage(data.default_message)}>
              Standardtext einsetzen
            </button>
            <button className="btn-primary" onClick={save} disabled={busy || !v.isValid}>
              {busy ? "Speichere…" : "Speichern"}
            </button>
          </div>
        </Panel>

        {/* Live-Vorschau (Discord Boost Card) */}
        <Panel title="Live-Vorschau">
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="dc-preview">
            <div className="dc-banner" style={image ? { backgroundImage: `url(${image})` } : undefined} />
            <div className="dc-body">
              <div className="grid h-[54px] w-[54px] place-items-center rounded-2xl bg-gradient-to-br from-accent to-violet text-xl font-bold text-accent-ink dc-av">
                B
              </div>
              <div className="dc-name">
                Booster
                <Icon name="sparkle" size={14} className="text-[var(--r-epic)]" />
              </div>
              <div className="dc-text whitespace-pre-wrap"><DiscordMarkdown text={preview} /></div>
            </div>
          </motion.div>
          <p className="mt-3 text-[0.8rem] text-faint">
            So sieht die Boost-Nachricht ungefähr aus (echte Werte beim Boost).
          </p>
        </Panel>
      </div>

      {/* Banner / Boost-Bild */}
      <Panel title="Banner / Boost-Bild">
        <p className="mb-4 text-sm text-muted">
          Optionales Bild oder GIF, das groß unter der Nachricht angezeigt wird. Per Drag &amp; Drop, Datei-Auswahl
          oder URL.
        </p>
        <ImageDropzone imageUrl={image} busy={imgBusy} onFile={uploadImage} onRemove={removeImage} label="Banner" />

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-start">
          <Field error={uv.showError("url")} className="flex-1">
            <input
              className="field"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onBlur={uv.blur("url")}
              placeholder="…oder Bild-URL einfügen (https://…)"
              onKeyDown={(e) => e.key === "Enter" && applyUrl()}
            />
          </Field>
          <button className="btn-ghost" onClick={applyUrl} disabled={imgBusy || !uv.isValid}>
            <Icon name="check" size={16} /> URL übernehmen
          </button>
        </div>
      </Panel>
    </>
  );
}
