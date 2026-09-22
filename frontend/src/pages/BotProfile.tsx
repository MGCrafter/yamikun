import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { ImageDropzone } from "../components/ui/ImageDropzone";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { maxLen, DISCORD } from "../lib/validators";

type BotProfileData = {
  nick: string;
  avatar: string | null;
  bot_name: string;
  global_avatar: string | null;
  can_change_nick: boolean;
};

export default function BotProfile() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<BotProfileData>(`/api/g/${gid}/botprofile`);

  const [nick, setNick] = useState("");
  const [avatar, setAvatar] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [imgBusy, setImgBusy] = useState(false);
  const v = useValidation({ nick }, { nick: [maxLen(DISCORD.NICK)] });

  useEffect(() => {
    if (data) {
      setNick(data.nick);
      setAvatar(data.avatar);
    }
  }, [data]);

  if (loading || !data) return <Spinner />;

  async function saveNick() {
    if (!v.validateAll()) return;
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/botprofile/nick`, { nick });
      push("ok", nick.trim() ? "Server-Nickname gesetzt." : "Nickname zurückgesetzt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function uploadAvatar(file: File) {
    const form = new FormData();
    form.append("image", file);
    setImgBusy(true);
    try {
      const r = await api.upload(`/api/g/${gid}/botprofile/avatar`, form);
      setAvatar(r.url);
      push("ok", "Server-Avatar gesetzt.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setImgBusy(false);
    }
  }

  async function removeAvatar() {
    setImgBusy(true);
    try {
      await api.post(`/api/g/${gid}/botprofile/avatar/remove`, {});
      setAvatar(null);
      push("ok", "Server-Avatar entfernt.");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setImgBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Bot-Serverprofil" subtitle="Name & Avatar des Bots auf diesem Server" />
      {!data.can_change_nick && (
        <InfoBanner>
          Dem Bot fehlt die Berechtigung „Nickname ändern" — der Name lässt sich evtl. nicht setzen.
        </InfoBanner>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Server-Nickname">
          <p className="mb-4 text-sm text-muted">
            So heißt <b>{data.bot_name || "der Bot"}</b> auf diesem Server. Leer lassen = globaler Name.
          </p>
          <Field label="Nickname" error={v.showError("nick")} className="mb-4">
            <input
              className="field"
              value={nick}
              onChange={(e) => setNick(e.target.value)}
              onBlur={v.blur("nick")}
              maxLength={32}
              placeholder={data.bot_name}
              onKeyDown={(e) => e.key === "Enter" && saveNick()}
            />
          </Field>
          <div className="flex items-center justify-between gap-3">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setNick("")}>
              Zurücksetzen
            </button>
            <button className="btn-primary" onClick={saveNick} disabled={busy || !v.isValid}>
              {busy ? "Speichere…" : "Nickname speichern"}
            </button>
          </div>
        </Panel>

        <Panel title="Server-Avatar">
          <p className="mb-4 text-sm text-muted">
            Server-spezifisches Bild des Bots. <b>Hinweis:</b> Discord unterstützt das für Bots nicht
            überall — schlägt es fehl, bleibt der globale Avatar.
          </p>
          <div className="max-w-[240px]">
            <ImageDropzone
              imageUrl={avatar}
              busy={imgBusy}
              onFile={uploadAvatar}
              onRemove={removeAvatar}
              label="Avatar"
              aspect="aspect-square"
            />
          </div>
          {!avatar && data.global_avatar && (
            <div className="mt-4 flex items-center gap-3 text-sm text-muted">
              <img src={data.global_avatar} alt="" className="h-10 w-10 rounded-full object-cover" />
              Aktuell: globaler Avatar
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
