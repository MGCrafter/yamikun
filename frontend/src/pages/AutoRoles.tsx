import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";

type RoleEntry = {
  id: string;
  name: string;
  color: string | null;
  assignable: boolean;
};

type AutoRolesData = {
  enabled: boolean;
  role_ids: string[];
  roles: RoleEntry[];
  can_manage_roles: boolean;
};

export default function AutoRoles() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading } = useApiData<AutoRolesData>(`/api/g/${gid}/autoroles`);

  const [enabled, setEnabled] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data) {
      setEnabled(data.enabled);
      // Gelöschte Rollen-IDs (nicht mehr in roles) herausfiltern, sonst bleiben
      // „tote" IDs in der Auswahl und würden beim Speichern erneut persistiert.
      setSelected(data.role_ids.filter((id) => data.roles.some((r) => r.id === id)));
    }
  }, [data]);

  if (loading || !data) return <Spinner />;

  function toggle(roleId: string) {
    setSelected((prev) =>
      prev.includes(roleId) ? prev.filter((id) => id !== roleId) : [...prev, roleId],
    );
  }

  async function save() {
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/autoroles`, { enabled, role_ids: selected });
      push("ok", "Auto-Rollen gespeichert.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Auto-Rollen" subtitle="Rollen automatisch beim Beitritt vergeben" />

      {!data.can_manage_roles && (
        <InfoBanner>
          Dem Bot fehlt die Berechtigung <strong>Rollen verwalten</strong> — Auto-Rollen können
          nicht vergeben werden, bis diese Berechtigung erteilt wird.
        </InfoBanner>
      )}

      <Panel title="Einstellungen">
        {/* An/Aus-Schalter */}
        <div className="toggle-card mb-5">
          <span>
            <span className="tc-label block">Aktiviert</span>
            <span className="block text-sm text-muted">
              Neue Mitglieder erhalten beim Beitritt die gewählten Rollen.
            </span>
          </span>
          <label className="switch">
            <input type="checkbox" checked={enabled} onChange={() => setEnabled((v) => !v)} />
            <span className="track" />
            <span className="thumb" />
          </label>
        </div>

        {/* Rollen-Auswahl */}
        <h3 className="mb-3 text-[15px] font-semibold">Rollen auswählen</h3>

        {data.roles.length === 0 ? (
          <p className="text-sm text-muted">Keine vergebbare Rolle gefunden.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {data.roles.map((role) => {
              const checked = selected.includes(role.id);
              const disabled = !role.assignable;
              return (
                <label
                  key={role.id}
                  className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                    disabled
                      ? "cursor-not-allowed border-border opacity-50"
                      : checked
                        ? "border-accent/40 bg-accent-soft"
                        : "border-border hover:border-border-strong hover:bg-surface-2"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => !disabled && toggle(role.id)}
                  />
                  {/* Farb-Punkt der Rolle */}
                  {role.color ? (
                    <span
                      className="inline-block h-3 w-3 flex-none rounded-full"
                      style={{ backgroundColor: role.color }}
                    />
                  ) : (
                    <span className="inline-block h-3 w-3 flex-none rounded-full bg-muted/40" />
                  )}
                  <span className="flex-1 text-[14px] font-medium">{role.name}</span>
                  {disabled && (
                    <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-semibold text-warning">
                      über Bot-Rolle
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <button className="btn-primary" onClick={save} disabled={busy}>
            {busy ? "Speichere…" : "Speichern"}
          </button>
        </div>
      </Panel>
    </>
  );
}
