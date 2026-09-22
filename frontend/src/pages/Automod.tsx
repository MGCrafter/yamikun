import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";

type ChannelEntry = { id: string; name: string };
type RoleEntry = { id: string; name: string; color: string | null };

type AutomodData = {
  enabled: boolean;
  delete_mass_mentions: boolean;
  exempt_role_ids: string[];
  honeypot_channel_ids: string[];
  honeypot_ban: boolean;
  honeypot_delete_seconds: number;
  channels: ChannelEntry[];
  roles: RoleEntry[];
  can_ban_members: boolean;
  can_manage_messages: boolean;
};

export default function Automod() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<AutomodData>(`/api/g/${gid}/automod`);

  const [enabled, setEnabled] = useState(false);
  const [deleteMassMentions, setDeleteMassMentions] = useState(true);
  const [honeypotChannelIds, setHoneypotChannelIds] = useState<string[]>([]);
  const [exemptRoleIds, setExemptRoleIds] = useState<string[]>([]);
  const [honeypotBan, setHoneypotBan] = useState(true);
  const [deleteDays, setDeleteDays] = useState(7);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setDeleteMassMentions(data.delete_mass_mentions);
    setHoneypotChannelIds(data.honeypot_channel_ids.filter((id) => data.channels.some((c) => c.id === id)));
    setExemptRoleIds(data.exempt_role_ids.filter((id) => data.roles.some((r) => r.id === id)));
    setHoneypotBan(data.honeypot_ban);
    setDeleteDays(Math.round(data.honeypot_delete_seconds / 86400));
  }, [data]);

  if (loading || !data) return <Spinner />;

  function toggle(list: string[], id: string, setList: (next: string[]) => void) {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }

  async function save() {
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/automod`, {
        enabled,
        delete_mass_mentions: deleteMassMentions,
        exempt_role_ids: exemptRoleIds,
        honeypot_channel_ids: honeypotChannelIds,
        honeypot_ban: honeypotBan,
        honeypot_delete_seconds: Math.max(0, Math.min(7, deleteDays)) * 86400,
      });
      push("ok", "AutoMod gespeichert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="AutoMod & Honeypot" subtitle="Spam-Bots automatisch abfangen und bannen" />

      {(!data.can_ban_members || !data.can_manage_messages) && (
        <InfoBanner>
          Dem Bot fehlen noch Berechtigungen: {!data.can_manage_messages && <strong>Nachrichten verwalten</strong>}
          {!data.can_manage_messages && !data.can_ban_members && " und "}
          {!data.can_ban_members && <strong>Mitglieder bannen</strong>}. Der Honeypot funktioniert erst sauber,
          wenn diese Rechte gesetzt sind.
        </InfoBanner>
      )}

      <Panel title="Grundschutz">
        <div className="toggle-card mb-3">
          <span>
            <span className="tc-label block">AutoMod aktiviert</span>
            <span className="block text-sm text-muted">Honeypot und Spam-Regeln greifen nur, wenn AutoMod aktiv ist.</span>
          </span>
          <label className="switch">
            <input type="checkbox" checked={enabled} onChange={() => setEnabled((v) => !v)} />
            <span className="track" />
            <span className="thumb" />
          </label>
        </div>
        <div className="toggle-card">
          <span>
            <span className="tc-label block">@everyone/@here löschen</span>
            <span className="block text-sm text-muted">Normale User können keine Massenpings spammen.</span>
          </span>
          <label className="switch">
            <input type="checkbox" checked={deleteMassMentions} onChange={() => setDeleteMassMentions((v) => !v)} />
            <span className="track" />
            <span className="thumb" />
          </label>
        </div>
      </Panel>

      <Panel title="Honeypot-Channels">
        <p className="mb-4 text-sm text-muted">
          Jeder normale User, der in einen dieser Channels schreibt, wird sofort behandelt. Admins, Mods und Ausnahme-Rollen sind geschützt.
        </p>
        {data.channels.length === 0 ? (
          <p className="text-sm text-muted">Keine Text-Channels gefunden.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {data.channels.map((channel) => {
              const checked = honeypotChannelIds.includes(channel.id);
              return (
                <label
                  key={channel.id}
                  className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                    checked ? "border-danger/40 bg-danger/10" : "border-border hover:border-border-strong hover:bg-surface-2"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="accent-danger"
                    checked={checked}
                    onChange={() => toggle(honeypotChannelIds, channel.id, setHoneypotChannelIds)}
                  />
                  <span className="flex-1 text-[14px] font-medium">#{channel.name}</span>
                  {checked && <span className="rounded-full bg-danger/15 px-2 py-0.5 text-[11px] font-semibold text-danger">Honeypot</span>}
                </label>
              );
            })}
          </div>
        )}

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div className="toggle-card">
            <span>
              <span className="tc-label block">User bannen</span>
              <span className="block text-sm text-muted">Empfohlen für echte Honeypot-Channels.</span>
            </span>
            <label className="switch">
              <input type="checkbox" checked={honeypotBan} onChange={() => setHoneypotBan((v) => !v)} />
              <span className="track" />
              <span className="thumb" />
            </label>
          </div>
          <label className="label flex flex-col gap-2">
            Nachrichten beim Ban löschen
            <select className="field" value={deleteDays} onChange={(e) => setDeleteDays(Number(e.target.value))}>
              <option value={0}>Keine alten Nachrichten</option>
              <option value={1}>Letzte 24 Stunden</option>
              <option value={3}>Letzte 3 Tage</option>
              <option value={7}>Letzte 7 Tage</option>
            </select>
          </label>
        </div>
      </Panel>

      <Panel title="Ausnahme-Rollen">
        <p className="mb-4 text-sm text-muted">Diese Rollen werden vom AutoMod ignoriert — zusätzlich zu Admins und Mods.</p>
        {data.roles.length === 0 ? (
          <p className="text-sm text-muted">Keine Rollen gefunden.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {data.roles.map((role) => {
              const checked = exemptRoleIds.includes(role.id);
              return (
                <label key={role.id} className="flex cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2.5 transition-colors hover:border-border-strong hover:bg-surface-2">
                  <input type="checkbox" className="accent-accent" checked={checked} onChange={() => toggle(exemptRoleIds, role.id, setExemptRoleIds)} />
                  {role.color ? <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: role.color }} /> : <span className="inline-block h-3 w-3 rounded-full bg-muted/40" />}
                  <span className="flex-1 text-[14px] font-medium">{role.name}</span>
                </label>
              );
            })}
          </div>
        )}
      </Panel>

      <div className="flex justify-end">
        <button className="btn-primary" onClick={save} disabled={busy}>
          {busy ? "Speichere…" : "Speichern"}
        </button>
      </div>
    </>
  );
}
