import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, errText } from "../lib/api";
import { useApiData } from "../lib/useApiData";
import { useToast } from "../components/ui/Toast";
import { InfoBanner, PageHeader, Panel, Spinner } from "../components/common";

type Category = { id: string; name: string };
type VoiceChannel = { id: string; name: string; category_id: string | null };
type ActiveVoice = { id: string; name: string; owner: string; members: number };
type VoiceData = {
  enabled: boolean;
  lobby_id: string | null;
  lobby_name: string | null;
  category_id: string | null;
  category_name: string | null;
  categories: Category[];
  voice_channels: VoiceChannel[];
  active_channels: ActiveVoice[];
  can_manage_channels: boolean;
  can_move_members: boolean;
};

const DEFAULT_LOBBY = "➕ Eigenen Channel erstellen";

export default function Voice() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<VoiceData>(`/api/g/${gid}/voice`);
  const [enabled, setEnabled] = useState(false);
  const [lobbyId, setLobbyId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [lobbyName, setLobbyName] = useState(DEFAULT_LOBBY);
  const [deleteLobby, setDeleteLobby] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setLobbyId(data.lobby_id ?? "");
    setCategoryId(data.category_id ?? "");
    setLobbyName(data.lobby_name ?? DEFAULT_LOBBY);
    setDeleteLobby(false);
  }, [data]);

  if (loading || !data) return <Spinner />;

  async function save() {
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/voice`, {
        enabled,
        lobby_id: lobbyId || null,
        category_id: categoryId || null,
        lobby_name: lobbyId ? null : (lobbyName.trim() || DEFAULT_LOBBY),
        delete_lobby: !enabled && deleteLobby,
      });
      push("ok", enabled ? "Join-to-Create wurde eingerichtet." : "Voice-System wurde deaktiviert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  function selectLobby(nextLobbyId: string) {
    setLobbyId(nextLobbyId);
    if (!nextLobbyId) return;
    const selected = data?.voice_channels.find((channel) => channel.id === nextLobbyId);
    if (selected) setCategoryId(selected.category_id ?? "");
  }

  const missingPermissions = !data.can_manage_channels || !data.can_move_members;

  return (
    <>
      <PageHeader
        title="Yami Voice"
        subtitle="Join-to-Create und persönliche Voice-Channels ohne Premium-Sperren"
      />

      {missingPermissions && (
        <InfoBanner>
          Yamis Bot-Rolle braucht noch
          {!data.can_manage_channels && <strong> Kanäle verwalten</strong>}
          {!data.can_manage_channels && !data.can_move_members && " und "}
          {!data.can_move_members && <strong> Mitglieder verschieben</strong>}.
          Ohne diese Rechte kann Join-to-Create keine Channels anlegen oder Mitglieder hineinziehen.
        </InfoBanner>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="eyebrow">Status</div>
          <div className={`mt-2 text-xl font-bold ${data.enabled ? "text-success" : "text-muted"}`}>
            {data.enabled ? "Aktiv" : "Deaktiviert"}
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="eyebrow">Lobby</div>
          <div className="mt-2 truncate font-semibold">{data.lobby_name ?? "Noch nicht erstellt"}</div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="eyebrow">Aktive Channels</div>
          <div className="mt-2 text-xl font-bold">{data.active_channels.length}</div>
        </div>
      </div>

      <Panel title="Join-to-Create einrichten">
        <div className="toggle-card mb-5">
          <span>
            <span className="tc-label block">Voice-System aktiviert</span>
            <span className="block text-sm text-muted">
              Wer die Lobby betritt, bekommt automatisch einen eigenen Voice-Channel.
            </span>
          </span>
          <label className="switch">
            <input type="checkbox" checked={enabled} onChange={() => setEnabled((value) => !value)} />
            <span className="track" />
            <span className="thumb" />
          </label>
        </div>

        {enabled ? (
          <div className="flex flex-col gap-4">
            <label className="label flex flex-col gap-2">
              Join-to-Create-Channel
              <select className="field" value={lobbyId} onChange={(event) => selectLobby(event.target.value)}>
                <option value="">— Yami soll eine neue Lobby erstellen —</option>
                {data.voice_channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>{channel.name}</option>
                ))}
              </select>
              <span className="text-xs text-muted">
                Wähle hier deinen bereits vorhandenen Voice-Channel. Dann verwendet Yami ihn als Lobby und erstellt keinen neuen.
              </span>
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="label flex flex-col gap-2">
                Voice-Kategorie
                <select className="field" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
                  <option value="">— Kategorie der Lobby verwenden / automatisch —</option>
                  {data.categories.map((category) => (
                    <option key={category.id} value={category.id}>{category.name}</option>
                  ))}
                </select>
                <span className="text-xs text-muted">Hier erscheinen Lobby und persönliche Channels.</span>
              </label>

              {lobbyId ? (
                <div className="rounded-md border border-success/25 bg-success/5 p-4 text-sm">
                  <div className="font-semibold text-success">Vorhandener Channel ausgewählt</div>
                  <p className="mt-1 text-muted">Yami übernimmt diesen Channel als Lobby und behält seinen Namen.</p>
                </div>
              ) : (
                <label className="label flex flex-col gap-2">
                  Name des neuen Join-to-Create-Channels
                  <input
                    className="field"
                    maxLength={100}
                    value={lobbyName}
                    onChange={(event) => setLobbyName(event.target.value)}
                    placeholder={DEFAULT_LOBBY}
                  />
                  <span className="text-xs text-muted">Nur nötig, wenn Yami eine neue Lobby anlegen soll.</span>
                </label>
              )}
            </div>
          </div>
        ) : (
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-danger/25 bg-danger/5 p-4">
            <input
              type="checkbox"
              className="mt-1 accent-danger"
              checked={deleteLobby}
              onChange={() => setDeleteLobby((value) => !value)}
              disabled={!data.lobby_id}
            />
            <span>
              <span className="block font-semibold">Lobby beim Deaktivieren löschen</span>
              <span className="text-sm text-muted">
                Ohne Haken bleibt der Lobby-Channel erhalten und kann später wieder aktiviert werden.
              </span>
            </span>
          </label>
        )}
      </Panel>

      <Panel title="Enthaltene Besitzer-Funktionen">
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {[
            "Channel umbenennen",
            "User-Limit einstellen",
            "Sperren und entsperren",
            "Verstecken und anzeigen",
            "User freigeben oder ausschließen",
            "Besitz übertragen oder übernehmen",
          ].map((feature) => (
            <div key={feature} className="rounded-md border border-border bg-surface-2 px-3 py-2.5">
              <span className="mr-2 text-success">✓</span>{feature}
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Aktive persönliche Channels">
        {data.active_channels.length === 0 ? (
          <p className="text-sm text-muted">Aktuell ist kein persönlicher Voice-Channel aktiv.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {data.active_channels.map((channel) => (
              <div key={channel.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3">
                <div>
                  <div className="font-semibold">{channel.name}</div>
                  <div className="text-xs text-muted">Besitzer: {channel.owner}</div>
                </div>
                <span className="rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent">
                  {channel.members} Mitglied{channel.members === 1 ? "" : "er"}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="flex justify-end">
        <button className="btn-primary" onClick={save} disabled={busy || (enabled && missingPermissions)}>
          {busy ? "Speichere…" : enabled ? "Einrichten & aktivieren" : "Deaktivieren"}
        </button>
      </div>
    </>
  );
}
