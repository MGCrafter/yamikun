import { useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText, type GameCfg, type GamesData } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Icon } from "../components/Icon";
import { NumberStepper } from "../components/ui/NumberStepper";
import { PageHeader, Panel, EmptyState, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, maxLen } from "../lib/validators";

export default function Games() {
  const { gid } = useParams();
  const { push } = useToast();
  const { data, loading, reload } = useApiData<GamesData>(`/api/g/${gid}/games`);

  const [newGame, setNewGame] = useState({ game: "", interval: "30", cap: "12", emoji: "" });
  const v = useValidation(
    { game: newGame.game },
    { game: [required("Bitte einen Spielnamen eingeben."), maxLen(100)] },
  );

  if (loading || !data) return <Spinner />;

  async function save(payload: Record<string, unknown>, okMsg: string) {
    try {
      await api.post(`/api/g/${gid}/games/add`, payload);
      push("ok", okMsg);
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function addGame(e: React.FormEvent) {
    e.preventDefault();
    if (!v.validateAll()) return;
    await save(newGame, "Spiel hinzugefügt.");
    setNewGame({ game: "", interval: "30", cap: "12", emoji: "" });
    v.reset();
  }

  async function removeGame(name: string) {
    if (!confirm(`Spiel „${name}“ entfernen?`)) return;
    try {
      await api.post(`/api/g/${gid}/games/remove`, { game: name });
      push("ok", "Spiel entfernt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function addAlias(game: string, alias: string) {
    try {
      await api.post(`/api/g/${gid}/games/alias`, { game, alias });
      push("ok", "Alias gespeichert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function removeAlias(alias: string) {
    try {
      await api.post(`/api/g/${gid}/games/alias/remove`, { alias });
      push("ok", "Alias entfernt.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function setChannel(channelId: string) {
    try {
      await api.post(`/api/g/${gid}/channel`, { channel_id: channelId });
      push("ok", "Drop-Channel gespeichert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  return (
    <>
      <PageHeader title="Spiele & Channel" subtitle={data.guild.name} />

      <Panel title="Belohnungs-Spiele">
        <p className="mb-4 text-sm text-muted">
          1 Booster-Pack je X Minuten Spielzeit, begrenzt auf Y Packs pro Tag — je Spiel einstellbar.
          Das Booster-Emote ist der <b>Name</b> eines Server-Emojis (z. B. <code className="rounded bg-bg2 px-1.5 py-0.5 text-accent">MeinBoosterEmote</code>); <b>leer lassen</b> = Standard 🎴.
        </p>

        <form onSubmit={addGame} className="mb-4 flex flex-wrap items-end gap-2.5">
          <Field label="Spiel" required error={v.showError("game")} className="min-w-[180px] flex-1">
            <input
              className="field"
              placeholder="Spielname (wie in Discord)"
              value={newGame.game}
              onChange={(e) => setNewGame({ ...newGame, game: e.target.value })}
              onBlur={v.blur("game")}
            />
          </Field>
          <label className="inline-flex items-center gap-1.5 text-[0.82rem] text-muted">
            alle
            <NumberStepper
              value={newGame.interval}
              min={1}
              max={1440}
              onChange={(v) => setNewGame({ ...newGame, interval: v })}
            />
            Min
          </label>
          <label className="inline-flex items-center gap-1.5 text-[0.82rem] text-muted">
            max
            <NumberStepper
              value={newGame.cap}
              min={1}
              max={100}
              onChange={(v) => setNewGame({ ...newGame, cap: v })}
            />
            /Tag
          </label>
          <button className="btn-primary" disabled={!v.isValid}>
            Hinzufügen
          </button>
        </form>

        {data.games.length === 0 ? (
          <EmptyState>Keine Spiele eingetragen.</EmptyState>
        ) : (
          <div className="flex flex-col gap-2">
            {data.games.map((g) => (
              <GameRow
                key={g.name}
                g={g}
                onSave={save}
                onRemove={removeGame}
                onAddAlias={addAlias}
                onRemoveAlias={removeAlias}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Karten-Drop-Channel">
        <p className="mb-4 text-sm text-muted">
          Wohin der Bot neue Karten-Drops meldet. Ohne Channel gehen sie per DM raus.
        </p>
        <select
          className="field"
          value={data.channel_id ?? ""}
          onChange={(e) => setChannel(e.target.value)}
        >
          <option value="">— DMs (kein Channel) —</option>
          {data.channels.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.name}
            </option>
          ))}
        </select>
      </Panel>
    </>
  );
}

function GameRow({
  g,
  onSave,
  onRemove,
  onAddAlias,
  onRemoveAlias,
}: {
  g: GameCfg;
  onSave: (p: Record<string, unknown>, msg: string) => void;
  onRemove: (name: string) => void;
  onAddAlias: (game: string, alias: string) => void;
  onRemoveAlias: (alias: string) => void;
}) {
  const [interval, setInterval] = useState(String(g.interval));
  const [cap, setCap] = useState(String(g.cap));
  const [emoji, setEmoji] = useState(g.emoji);
  const [alias, setAlias] = useState("");

  function submitAlias(e: React.FormEvent) {
    e.preventDefault();
    const clean = alias.trim();
    if (!clean) return;
    onAddAlias(g.name, clean);
    setAlias("");
  }

  return (
    <div className="flex items-start gap-2">
      <div className="flex flex-1 flex-col gap-2 rounded-md border border-border bg-surface-2 px-3.5 py-2.5">
        <div className="flex flex-wrap items-center gap-3.5">
          <span className="inline-flex min-w-[150px] flex-1 items-center gap-2 truncate font-semibold">
            <span className="text-faint">
              <Icon name="gamepad" size={16} />
            </span>
            <span className="truncate">{g.name}</span>
          </span>
          <label className="inline-flex items-center gap-1.5 text-[0.82rem] text-muted">
            alle
            <NumberStepper value={interval} min={1} max={1440} onChange={setInterval} />
            Min
          </label>
          <label className="inline-flex items-center gap-1.5 text-[0.82rem] text-muted">
            max
            <NumberStepper value={cap} min={1} max={100} onChange={setCap} />
            /Tag
          </label>
          <label className="inline-flex items-center gap-1.5 text-[0.82rem] text-muted">
            Emote
            <input
              className="field w-52 px-2 py-1.5"
              value={emoji}
              placeholder="Server-Emoji-Name (leer = 🎴)"
              onChange={(e) => setEmoji(e.target.value)}
            />
          </label>
          <button
            className="btn-primary px-3.5 py-2 text-[0.82rem]"
            onClick={() => onSave({ game: g.name, interval, cap, emoji }, "Gespeichert.")}
          >
            Speichern
          </button>
        </div>
        <form onSubmit={submitAlias} className="flex flex-wrap items-center gap-2 text-[0.82rem] text-muted">
          <span>Zusätzliche Discord-Namen:</span>
          {g.aliases.length === 0 ? (
            <span className="text-faint">keine</span>
          ) : (
            g.aliases.map((a) => (
              <button
                key={a}
                type="button"
                className="rounded-full border border-border bg-bg2 px-2 py-1 text-fg hover:border-danger"
                title="Alias entfernen"
                onClick={() => onRemoveAlias(a)}
              >
                {a} ×
              </button>
            ))
          )}
          <input
            className="field w-52 px-2 py-1.5"
            value={alias}
            placeholder="z.B. Valorant Tracker"
            onChange={(e) => setAlias(e.target.value)}
          />
          <button className="btn-secondary px-3 py-1.5" disabled={!alias.trim()}>
            Alias hinzufügen
          </button>
        </form>
      </div>
      <button title="Entfernen" onClick={() => onRemove(g.name)} className="icon-btn flex-none">
        <Icon name="x" size={16} />
      </button>
    </div>
  );
}
