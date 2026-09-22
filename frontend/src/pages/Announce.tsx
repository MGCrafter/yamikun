import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { motion } from "motion/react";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { ImageDropzone } from "../components/ui/ImageDropzone";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, InfoBanner, EmptyState, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, maxLen, DISCORD } from "../lib/validators";
import { DiscordMarkdown } from "../components/DiscordMarkdown";

type Role = { id: string; name: string; color: string | null };
type Emoji = { name: string; code: string; url: string };
type SentMessage = {
  id: number;
  channel_id: string;
  channel_name: string | null;
  as_embed: boolean;
  title: string;
  content: string;
  color: string;
  image: string | null;
  ping_roles: string[];
  created_at: number;
  link: string;
};
type AnnounceData = {
  channels: { id: string; name: string }[];
  roles: Role[];
  emojis: Emoji[];
  messages: SentMessage[];
};

const COMMON_EMOJIS = ["🎉", "🔥", "✅", "❗", "⚠️", "📢", "🎁", "⭐", "❤️", "😎", "👀", "🚀"];

export default function Announce() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<AnnounceData>(`/api/g/${gid}/announce`);

  const [channelId, setChannelId] = useState("");
  const [content, setContent] = useState("");
  const [asEmbed, setAsEmbed] = useState(false);
  const [title, setTitle] = useState("");
  const [color, setColor] = useState("#7C3AED");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const [existingImage, setExistingImage] = useState<string | null>(null);
  const [removeImage, setRemoveImage] = useState(false);
  const [pingRoles, setPingRoles] = useState<string[]>([]);
  const [showRoles, setShowRoles] = useState(false);
  const [showEmojis, setShowEmojis] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [listFilter, setListFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const topRef = useRef<HTMLDivElement>(null);

  // Beim Bearbeiten ist der Channel fix → dann nicht als Pflichtfeld prüfen.
  const v = useValidation(
    { channel_id: channelId, title, content },
    {
      channel_id: editingId !== null ? [] : [required("Bitte einen Channel wählen.")],
      title: asEmbed ? [maxLen(DISCORD.EMBED_TITLE)] : [],
      content: [maxLen(asEmbed ? DISCORD.EMBED_DESC : DISCORD.MESSAGE)],
    },
  );

  useEffect(() => {
    if (!imageFile) {
      setFilePreview(null);
      return;
    }
    const url = URL.createObjectURL(imageFile);
    setFilePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile]);

  if (loading || !data) return <Spinner />;

  const preview = filePreview ?? (existingImage && !removeImage ? existingImage : null);
  const hasBody =
    content.trim() !== "" ||
    !!preview ||
    pingRoles.length > 0 ||
    (asEmbed && title.trim() !== "");
  const canSubmit = (editingId !== null || !!channelId) && hasBody;
  const pingedRoles = data.roles.filter((r) => pingRoles.includes(r.id));

  function insert(token: string) {
    const ta = taRef.current;
    if (!ta) {
      setContent((m) => m + token);
      return;
    }
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    setContent((m) => m.slice(0, start) + token + m.slice(end));
    requestAnimationFrame(() => {
      ta.focus();
      ta.selectionStart = ta.selectionEnd = start + token.length;
    });
  }

  function toggleRole(id: string) {
    setPingRoles((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }

  function resetComposer() {
    setEditingId(null);
    setContent("");
    setTitle("");
    setImageFile(null);
    setExistingImage(null);
    setRemoveImage(false);
    setPingRoles([]);
  }

  function startEdit(m: SentMessage) {
    setEditingId(m.id);
    setChannelId(m.channel_id);
    setContent(m.content);
    setAsEmbed(m.as_embed);
    setTitle(m.title);
    setColor(m.color?.startsWith("#") ? m.color : "#7C3AED");
    setPingRoles(m.ping_roles);
    setShowRoles(m.ping_roles.length > 0);
    setImageFile(null);
    setExistingImage(m.image);
    setRemoveImage(false);
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submit() {
    if (!v.validateAll()) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("content", content);
      form.append("as_embed", asEmbed ? "1" : "");
      if (asEmbed) {
        form.append("title", title);
        form.append("color", color);
      }
      if (pingRoles.length) form.append("ping_roles", pingRoles.join(","));
      if (imageFile) form.append("image", imageFile);
      if (editingId !== null) {
        form.append("id", String(editingId));
        if (removeImage && !imageFile) form.append("remove_image", "1");
        await api.upload(`/api/g/${gid}/announce/edit`, form);
        push("ok", "Nachricht aktualisiert.");
      } else {
        form.append("channel_id", channelId);
        await api.upload(`/api/g/${gid}/announce/send`, form);
        push("ok", "Nachricht gesendet.");
      }
      resetComposer();
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function del(m: SentMessage) {
    if (!confirm("Diese Nachricht auch auf Discord löschen?")) return;
    try {
      await api.post(`/api/g/${gid}/announce/delete`, { id: m.id, delete_message: true });
      push("ok", "Nachricht gelöscht.");
      if (editingId === m.id) resetComposer();
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  const editing = editingId !== null;
  const messages = data.messages.filter((m) => !listFilter || m.channel_id === listFilter);

  return (
    <>
      <div ref={topRef} />
      <PageHeader title="Nachricht senden" subtitle="Den Bot in einen Channel schreiben lassen" />
      {editing && (
        <InfoBanner>
          Du bearbeitest eine gesendete Nachricht. Der Channel lässt sich dabei nicht ändern.
        </InfoBanner>
      )}
      {!editing && !channelId && <InfoBanner>Wähle einen Ziel-Channel.</InfoBanner>}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title={editing ? "Bearbeiten" : "Verfassen"}>
          <Field label="Channel" required={!editing} error={v.showError("channel_id")} className="mb-5">
            <select
              className="field"
              value={channelId}
              disabled={editing}
              onChange={(e) => setChannelId(e.target.value)}
              onBlur={v.blur("channel_id")}
            >
              <option value="">— Channel wählen —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </Field>

          <div className="toggle-card mb-5">
            <span>
              <span className="tc-label block">Als Embed senden</span>
              <span className="block text-sm text-muted">Hervorgehoben mit Titel, Farbe & Bild.</span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={asEmbed} onChange={() => setAsEmbed((v) => !v)} />
              <span className="track" />
              <span className="thumb" />
            </label>
          </div>

          {asEmbed && (
            <div className="mb-4 flex flex-col gap-3 sm:flex-row">
              <Field label="Titel" error={v.showError("title")} className="flex-1">
                <input
                  className="field"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  onBlur={v.blur("title")}
                  maxLength={256}
                  placeholder="z.B. 📢 Ankündigung"
                />
              </Field>
              <label className="flex flex-col gap-2 label">
                Farbe
                <input
                  type="color"
                  className="field h-[42px] w-16 cursor-pointer p-1"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                />
              </label>
            </div>
          )}

          {/* Rollen pingen — einklappbar */}
          {data.roles.length > 0 && (
            <div className="mb-4">
              <button
                type="button"
                onClick={() => setShowRoles((v) => !v)}
                className="flex w-full items-center justify-between rounded-md border border-border bg-surface-2 px-3 py-2 text-left transition-colors hover:border-border-strong"
              >
                <span className="eyebrow">
                  Rollen pingen (optional){pingRoles.length ? ` · ${pingRoles.length} gewählt` : ""}
                </span>
                <Icon name={showRoles ? "minus" : "plus"} size={15} />
              </button>
              {showRoles && (
                <>
                  <div className="sidebar-scroll mt-2 flex max-h-44 flex-wrap gap-2 overflow-y-auto">
                    {data.roles.map((r) => {
                      const on = pingRoles.includes(r.id);
                      return (
                        <button
                          key={r.id}
                          type="button"
                          onClick={() => toggleRole(r.id)}
                          className={`var-chip inline-flex items-center gap-1.5 ${
                            on ? "border-accent bg-[var(--accent-soft)] text-txt" : ""
                          }`}
                        >
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ background: r.color ?? "var(--faint)" }}
                          />
                          @{r.name}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-2 text-[0.78rem] text-faint">
                    Damit der Ping ankommt, muss der Bot „Alle Rollen erwähnen" dürfen oder die Rolle
                    „erwähnbar" sein. Bei Embeds wird der Ping als Text über dem Embed gesendet.
                  </p>
                </>
              )}
            </div>
          )}

          {/* Textblock (zuerst) */}
          <div className="mb-2 flex items-center justify-between">
            <span className="label">Nachricht</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowEmojis((v) => !v)}>
              <Icon name="sparkle" size={15} /> Emoji
            </button>
          </div>
          {showEmojis && (
            <div className="mb-2 max-h-40 overflow-y-auto sidebar-scroll rounded-md border border-border bg-surface-2 p-2.5">
              <div className="flex flex-wrap gap-1.5">
                {COMMON_EMOJIS.map((e) => (
                  <button
                    key={e}
                    type="button"
                    onClick={() => insert(e)}
                    className="grid h-8 w-8 place-items-center rounded-md text-lg hover:bg-surface-3"
                  >
                    {e}
                  </button>
                ))}
              </div>
              {data.emojis.length > 0 && (
                <>
                  <div className="eyebrow my-2">Server-Emojis</div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.emojis.map((e) => (
                      <button
                        key={e.code}
                        type="button"
                        title={`:${e.name}:`}
                        onClick={() => insert(e.code)}
                        className="grid h-8 w-8 place-items-center rounded-md hover:bg-surface-3"
                      >
                        <img src={e.url} alt={e.name} className="h-6 w-6 object-contain" />
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          <Field error={v.showError("content")}>
            <textarea
              ref={taRef}
              className="field min-h-[150px] resize-y font-sans"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onBlur={v.blur("content")}
              placeholder="Dein Text — Zeilenumbrüche bleiben erhalten. @everyone wird nicht gepingt."
            />
          </Field>
          <p className="mb-4 mt-2 text-[0.78rem] text-faint">
            Tipp: Eine Rolle pingst du mit <code className="rounded bg-surface-2 px-1">{"<@&ROLLEN_ID>"}</code> im
            Text (Rollen-ID, nicht der Name). Bei Embeds nur außerhalb des Embed-Texts — am einfachsten
            über die Rollen-Auswahl oben.
          </p>

          {/* Bild (danach) */}
          <div className="mb-4">
            <span className="eyebrow mb-2 block">Bild (optional)</span>
            <ImageDropzone
              imageUrl={preview}
              onFile={(f) => {
                setImageFile(f);
                setRemoveImage(false);
              }}
              onRemove={() => {
                setImageFile(null);
                if (existingImage) setRemoveImage(true);
              }}
              label="Bild"
            />
          </div>

          <div className="mt-4 flex items-center justify-end gap-2">
            {editing && (
              <button type="button" className="btn-ghost" onClick={resetComposer}>
                Abbrechen
              </button>
            )}
            <button className="btn-primary" onClick={submit} disabled={busy || !canSubmit || !v.isValid}>
              {busy ? "…" : editing ? (
                <>
                  <Icon name="check" size={16} /> Aktualisieren
                </>
              ) : (
                <>
                  <Icon name="enter" size={16} /> Senden
                </>
              )}
            </button>
          </div>
        </Panel>

        <Panel title="Vorschau">
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="dc-preview sidebar-scroll max-h-[460px] overflow-y-auto">
            <div className="dc-body">
              {pingedRoles.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {pingedRoles.map((r) => (
                    <span
                      key={r.id}
                      className="rounded px-1.5 py-0.5 text-[0.85rem] font-medium"
                      style={{
                        color: r.color ?? "var(--accent)",
                        background: "color-mix(in oklab, var(--accent) 16%, transparent)",
                      }}
                    >
                      @{r.name}
                    </span>
                  ))}
                </div>
              )}
              {asEmbed ? (
                <div className="rounded-md border-l-4 bg-surface-2 p-4" style={{ borderColor: color }}>
                  {title && <div className="mb-1 font-bold text-txt">{title}</div>}
                  <div className="dc-text whitespace-pre-wrap"><DiscordMarkdown text={content} /></div>
                  {preview && (
                    <img src={preview} alt="" className="mt-3 max-h-64 w-full rounded-md object-cover" />
                  )}
                </div>
              ) : (
                <>
                  <div className="dc-text whitespace-pre-wrap">
                    {content || preview || pingedRoles.length ? <DiscordMarkdown text={content} /> : "…"}
                  </div>
                  {preview && (
                    <img src={preview} alt="" className="mt-2 max-h-64 w-full rounded-md object-cover" />
                  )}
                </>
              )}
            </div>
          </motion.div>
          <p className="mt-3 text-[0.8rem] text-faint">So erscheint die Nachricht ungefähr im Channel.</p>
        </Panel>
      </div>

      {/* Zuletzt gesendet — bearbeiten */}
      <Panel title="Zuletzt gesendet">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted">{messages.length} Nachricht(en)</span>
          <select
            className="field mb-0 ml-auto max-w-[240px]"
            value={listFilter}
            onChange={(e) => setListFilter(e.target.value)}
          >
            <option value="">Alle Channels</option>
            {data.channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
        </div>

        {messages.length === 0 ? (
          <EmptyState icon="hash">Noch keine Nachrichten gesendet.</EmptyState>
        ) : (
          <div className="sidebar-scroll flex max-h-[520px] flex-col gap-2 overflow-y-auto pr-1">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex items-center gap-3 rounded-md border bg-surface-2 p-3 ${
                  editingId === m.id ? "border-accent" : "border-border"
                }`}
              >
                {m.image ? (
                  <img src={m.image} alt="" className="h-11 w-11 shrink-0 rounded object-cover" />
                ) : (
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded bg-surface-3 text-muted">
                    <Icon name={m.as_embed ? "layers" : "hash"} size={18} />
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-semibold">
                    {m.title || m.content || (m.image ? "Bild" : "(leer)")}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-muted">
                    <span>#{m.channel_name ?? m.channel_id}</span>
                    <span>·</span>
                    <span>{m.as_embed ? "Embed" : "Text"}</span>
                    {m.ping_roles.length > 0 && (
                      <>
                        <span>·</span>
                        <span>{m.ping_roles.length} Ping</span>
                      </>
                    )}
                    <span>·</span>
                    <span>{new Date(m.created_at * 1000).toLocaleString("de-DE")}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <a
                    href={m.link}
                    target="_blank"
                    rel="noopener"
                    title="Auf Discord öffnen"
                    className="grid h-8 w-8 place-items-center rounded-lg border border-border text-muted hover:border-accent hover:text-accent"
                  >
                    <Icon name="enter" size={15} />
                  </a>
                  <button
                    type="button"
                    title="Bearbeiten"
                    onClick={() => startEdit(m)}
                    className="grid h-8 w-8 place-items-center rounded-lg border border-border text-muted hover:border-accent hover:text-accent"
                  >
                    <Icon name="edit" size={15} />
                  </button>
                  <button
                    type="button"
                    title="Löschen"
                    onClick={() => del(m)}
                    className="grid h-8 w-8 place-items-center rounded-lg border border-border text-muted hover:border-danger hover:text-danger"
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
