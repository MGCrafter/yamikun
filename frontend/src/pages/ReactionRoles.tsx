import { useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, EmptyState, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, snowflake } from "../lib/validators";

type Binding = {
  channel_id: string;
  channel_name: string | null;
  message_id: string;
  message_link: string;
  emoji: { raw: string; label: string; image: string | null };
  role_id: string;
  role_name: string | null;
  role_color: string | null;
  required_role_id: string | null;
  required_role_name: string | null;
};
type RRData = {
  bindings: Binding[];
  roles: { id: string; name: string; color: string | null; assignable: boolean }[];
  requirement_roles: { id: string; name: string; color: string | null }[];
  channels: { id: string; name: string }[];
  emojis: { key: string; name: string; image: string }[];
};

type Row = { emoji: string; roleId: string; reqRoleId: string };
const isCustom = (s: string) => /:\d{13,20}$/.test(s);

// Kuratierte Standard-Discord-Emojis zum Anklicken (für Reaction Roles).
// Gruppiert, damit der Picker übersichtlich bleibt; deckt die typischen
// Einsatzfälle ab (Verify/News/Gamer/Farben/Zahlen …).
const UNICODE_EMOJIS: { label: string; items: string[] }[] = [
  { label: "Beliebt", items: ["✅", "❌", "⭐", "🔥", "💜", "🎮", "🎉", "👍", "👎", "🔔", "📢", "💯"] },
  { label: "Smileys", items: ["😀", "😄", "😁", "😂", "🤣", "😊", "😍", "😎", "🤩", "🥳", "🤔", "😴", "😇", "🙃", "😉", "🥺"] },
  { label: "Gesten", items: ["👋", "🙌", "👏", "🙏", "💪", "🤝", "✌️", "🤞", "👌", "🤙", "👀", "🫶"] },
  { label: "Spiele & Aktivität", items: ["🎮", "🕹️", "🎲", "🎯", "🏆", "🥇", "⚽", "🏀", "🎧", "🎵", "🎬", "🎨", "📚", "💻"] },
  { label: "Symbole", items: ["🌟", "✨", "⚡", "💥", "❄️", "🌈", "☀️", "🌙", "💧", "🍀", "🌸", "♻️", "⚠️", "❤️", "🧡", "💛", "💚", "💙", "🤍", "🖤"] },
  { label: "Farben", items: ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "⚫", "🟤", "🟥", "🟧", "🟨", "🟩", "🟦", "🟪"] },
  { label: "Zahlen", items: ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"] },
];

function EmojiView({ emoji }: { emoji: Binding["emoji"] }) {
  if (emoji.image)
    return <img src={emoji.image} alt={emoji.label} className="inline-block h-5 w-5 align-middle" />;
  return <span className="text-lg leading-none">{emoji.raw}</span>;
}

// Kleine Emoji-Vorschau (Unicode-Char oder Custom-CDN-Bild) für die Eingabe.
function EmojiSwatch({ value }: { value: string }) {
  return (
    <span className="rr-emoji flex-none">
      {value ? (
        isCustom(value) ? (
          <img src={`https://cdn.discordapp.com/emojis/${value.split(":").pop()}.png`} alt="" className="h-6 w-6" />
        ) : (
          <span className="text-xl">{value}</span>
        )
      ) : (
        <span className="text-faint">?</span>
      )}
    </span>
  );
}

export default function ReactionRoles() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<RRData>(`/api/g/${gid}/reactionroles`);

  const [channelId, setChannelId] = useState("");
  const [messageId, setMessageId] = useState("");
  const [rows, setRows] = useState<Row[]>([{ emoji: "", roleId: "", reqRoleId: "" }]);
  const [activeRow, setActiveRow] = useState(0);
  const [busy, setBusy] = useState(false);
  const v = useValidation(
    { channel_id: channelId, message_id: messageId },
    {
      channel_id: [required("Bitte den Channel der Nachricht wählen.")],
      message_id: [
        required("Bitte die Nachrichten-ID angeben."),
        snowflake("Ungültige Nachrichten-ID (nur Ziffern, 15–21 Stellen)."),
      ],
    },
  );

  if (loading || !data) return <Spinner />;

  const validCount = rows.filter((r) => r.emoji && r.roleId).length;

  const updateRow = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addRow = () => {
    setRows((rs) => [...rs, { emoji: "", roleId: "", reqRoleId: "" }]);
    setActiveRow(rows.length);
  };
  const removeRow = (i: number) =>
    setRows((rs) => (rs.length === 1 ? [{ emoji: "", roleId: "", reqRoleId: "" }] : rs.filter((_, idx) => idx !== i)));

  async function createAll() {
    if (!v.validateAll()) return;
    // Leerzeichen trimmen und offensichtlich ungültige Emoji-Strings ablehnen.
    const trimmed = rows.map((r) => ({ ...r, emoji: r.emoji.trim() }));
    const tooLong = trimmed.some((r) => r.emoji.length > 64);
    if (tooLong) {
      push("err", "Emoji-Feld ist zu lang — bitte einen gültigen Emoji eingeben (max. 64 Zeichen).");
      return;
    }
    const valid = trimmed.filter((r) => r.emoji && r.roleId);
    if (valid.length === 0) {
      push("err", "Mindestens eine Zeile mit Emoji + Rolle ausfüllen.");
      return;
    }
    setBusy(true);
    let ok = 0;
    let fail = 0;
    let lastErr = "";
    for (const r of valid) {
      try {
        await api.post(`/api/g/${gid}/reactionroles/add`, {
          channel_id: channelId,
          message_id: messageId,
          emoji: r.emoji,
          role_id: r.roleId,
          required_role_id: r.reqRoleId || "",
        });
        ok++;
      } catch (e) {
        fail++;
        lastErr = errText(e);
      }
    }
    // Bei Fehlern den konkreten Grund mitgeben statt nur "X fehlgeschlagen".
    push(
      fail ? "err" : "ok",
      `${ok} Bindung(en) angelegt${fail ? `, ${fail} fehlgeschlagen${lastErr ? `: ${lastErr}` : ""}` : ""}.`,
    );
    setRows([{ emoji: "", roleId: "", reqRoleId: "" }]); // Channel + Nachricht bleiben für weitere Bindungen
    setActiveRow(0);
    reload();
    setBusy(false);
  }

  async function del(b: Binding) {
    if (!confirm(`Bindung ${b.emoji.label} → ${b.role_name ?? b.role_id} entfernen?`)) return;
    try {
      await api.post(`/api/g/${gid}/reactionroles/delete`, { message_id: b.message_id, emoji: b.emoji.raw });
      push("ok", "Bindung entfernt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  return (
    <>
      <PageHeader title="Reaction Roles" subtitle={`${data.bindings.length} Bindungen`} />
      <InfoBanner>
        Mitglieder bekommen die Rolle, wenn sie mit dem Emoji auf die Nachricht reagieren — und verlieren
        sie wieder beim Entfernen der Reaktion. Optional lässt sich pro Zeile eine{" "}
        <b>Voraussetzungs-Rolle</b> wählen: Wer sie nicht hat, bekommt die Rolle nicht und dessen
        Reaktion wird automatisch entfernt.
      </InfoBanner>

      <Panel title="Reaktionen hinzufügen">
        <p className="mb-4 text-sm text-muted">
          Channel &amp; Nachricht einmal wählen, dann beliebig viele Emoji&#8202;→&#8202;Rollen-Zeilen
          ergänzen und mit einem Klick alle auf <b>dieselbe</b> Nachricht legen.
        </p>

        {/* Channel + Nachricht (einmalig) */}
        <div className="mb-5 grid gap-4 sm:grid-cols-2">
          <Field label="Channel der Nachricht" required error={v.showError("channel_id")}>
            <select
              className="field"
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              onBlur={v.blur("channel_id")}
            >
              <option value="">— wählen —</option>
              {data.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Nachrichten-ID" required error={v.showError("message_id")}>
            <input
              className="field"
              value={messageId}
              onChange={(e) => setMessageId(e.target.value)}
              onBlur={v.blur("message_id")}
              inputMode="numeric"
              placeholder="Rechtsklick auf Nachricht → ID kopieren"
            />
          </Field>
        </div>

        {/* Emoji → Rolle Zeilen */}
        <div className="eyebrow mb-2">Emoji → Rolle</div>
        <div className="flex flex-col gap-2.5">
          {rows.map((row, i) => (
            <div
              key={i}
              onMouseDown={() => setActiveRow(i)}
              className={`flex flex-col gap-2.5 rounded-md border p-2.5 transition-all duration-300 ${
                activeRow === i
                  ? "border-accent/55 bg-surface-2 shadow-[0_0_0_3px_var(--accent-soft)]"
                  : "border-border bg-surface-2"
              }`}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="flex flex-col gap-0.5 sm:w-1/2">
                  <div className="flex items-center gap-2">
                    <EmojiSwatch value={row.emoji} />
                    <input
                      className="field flex-1"
                      value={row.emoji}
                      onFocus={() => setActiveRow(i)}
                      onChange={(e) => updateRow(i, { emoji: e.target.value })}
                      placeholder="Emoji unten wählen oder tippen"
                    />
                  </div>
                  {busy === false && row.roleId && !row.emoji.trim() && (
                    <span className="pl-8 text-xs text-danger">Bitte ein Emoji eingeben.</span>
                  )}
                </div>
                <select
                  className="field sm:w-1/2"
                  value={row.roleId}
                  onChange={(e) => updateRow(i, { roleId: e.target.value })}
                >
                  <option value="">— Rolle wählen —</option>
                  {data.roles.map((r) => (
                    <option key={r.id} value={r.id} disabled={!r.assignable}>
                      {r.name}
                      {!r.assignable ? "  (über Bot-Rolle)" : ""}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => removeRow(i)}
                  title="Zeile entfernen"
                  className="grid h-9 w-9 flex-none place-items-center self-end rounded-lg text-faint transition hover:bg-danger/10 hover:text-danger sm:self-auto"
                >
                  <Icon name="x" size={16} />
                </button>
              </div>
              {/* Optionale Voraussetzung: nur Mitglieder mit dieser Rolle bekommen die Reaction Role. */}
              <div className="flex items-center gap-2 sm:pl-8">
                <Icon name="users" size={14} className="flex-none text-faint" />
                <span className="flex-none text-xs text-faint">nur für</span>
                <select
                  className="field flex-1"
                  value={row.reqRoleId}
                  onChange={(e) => updateRow(i, { reqRoleId: e.target.value })}
                >
                  <option value="">— alle dürfen (keine Voraussetzung) —</option>
                  {data.requirement_roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>

        <button type="button" onClick={addRow} className="add-row">
          <span className="grid h-5 w-5 place-items-center rounded-md bg-surface-3 text-base leading-none">+</span>
          Weitere Zeile
        </button>

        {/* Standard-Emoji-Picker (Unicode) → füllt die aktive Zeile */}
        <div className="emoji-box mt-2">
          <div className="eyebrow mb-3">
            Standard-Emojis <span className="normal-case text-faint/70">— füllt die markierte Zeile</span>
          </div>
          <div className="max-h-56 overflow-y-auto pr-1">
            {UNICODE_EMOJIS.map((grp) => (
              <div key={grp.label} className="mb-3 last:mb-0">
                <div className="mb-1.5 text-[0.7rem] uppercase tracking-wide text-faint/70">{grp.label}</div>
                <div className="emoji-grid">
                  {grp.items.map((em) => (
                    <button
                      type="button"
                      key={em}
                      title={em}
                      onClick={() => updateRow(activeRow, { emoji: em })}
                      className="emoji-cell"
                    >
                      <span className="text-xl leading-none">{em}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Server-Emoji-Picker → füllt die aktive Zeile */}
        {data.emojis.length > 0 && (
          <div className="emoji-box mt-2">
            <div className="eyebrow mb-3">
              Server-Emojis <span className="normal-case text-faint/70">— füllt die markierte Zeile</span>
            </div>
            <div className="emoji-grid">
              {data.emojis.map((e) => (
                <button
                  type="button"
                  key={e.key}
                  title={`:${e.name}:`}
                  onClick={() => updateRow(activeRow, { emoji: e.key })}
                  className="emoji-cell"
                >
                  <img src={e.image} alt={e.name} className="h-6 w-6" />
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <button className="btn-primary" onClick={createAll} disabled={busy || validCount === 0 || !v.isValid}>
            {busy ? "Lege an…" : `Alle anlegen${validCount ? ` (${validCount})` : ""}`}
          </button>
        </div>
      </Panel>

      <Panel title="Bestehende Bindungen">
        {data.bindings.length === 0 ? (
          <EmptyState icon="users">Noch keine Reaction Roles angelegt.</EmptyState>
        ) : (
          <div className="list">
            {data.bindings.map((b) => (
              <div
                key={`${b.message_id}-${b.emoji.raw}`}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 transition-colors hover:border-border-strong"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <EmojiView emoji={b.emoji} />
                  <Icon name="arrow" size={15} className="text-faint" />
                  <span
                    className="truncate rounded-md px-2 py-0.5 text-sm font-semibold"
                    style={{
                      color: b.role_color ?? undefined,
                      background: b.role_color ? `${b.role_color}22` : "transparent",
                    }}
                  >
                    {b.role_name ? `@${b.role_name}` : `Rolle ${b.role_id}`}
                  </span>
                  {b.required_role_id && (
                    <span className="hidden items-center gap-1 rounded-md bg-surface-3 px-2 py-0.5 text-[0.72rem] text-faint sm:inline-flex">
                      <Icon name="users" size={12} />
                      nur @{b.required_role_name ?? b.required_role_id}
                    </span>
                  )}
                  <a
                    href={b.message_link}
                    target="_blank"
                    rel="noreferrer"
                    className="hidden text-[0.8rem] text-faint hover:text-accent sm:inline"
                  >
                    #{b.channel_name ?? "?"} · Nachricht ↗
                  </a>
                </div>
                <button
                  onClick={() => del(b)}
                  title="Entfernen"
                  className="grid h-8 w-8 flex-none place-items-center rounded-lg text-faint transition hover:bg-danger/10 hover:text-danger"
                >
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
