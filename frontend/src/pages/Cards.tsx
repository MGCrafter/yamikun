import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText, type Card } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";
import { CardTile } from "../components/ui/CardTile";
import { FileUpload } from "../components/ui/file-upload";
import { Icon } from "../components/Icon";
import { PageHeader, Panel, EmptyState, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, maxLen } from "../lib/validators";

type CardsData = { can_edit: boolean; games: string[]; cards: Card[] };

export default function Cards() {
  const { gid } = useParams();
  const { me } = useAuth();
  const { push, update } = useToast();
  const { data, loading, reload } = useApiData<CardsData>(`/api/g/${gid}/cards`);
  const [sort, setSort] = useState<"game" | "rarity">("game");

  // Upload-Formular-State
  const [game, setGame] = useState("");
  const [name, setName] = useState("");
  const [rarity, setRarity] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadKey, setUploadKey] = useState(0); // remount -> Upload-Feld nach Erfolg leeren
  const [busy, setBusy] = useState(false);

  // Spiel-Anfrage (nur für Nicht-Owner)
  const [reqGame, setReqGame] = useState("");
  const [reqNote, setReqNote] = useState("");
  const [reqBusy, setReqBusy] = useState(false);
  const [reqSent, setReqSent] = useState(false);

  const v = useValidation(
    { game, name, rarity, image: file },
    {
      game: [required("Bitte ein Spiel wählen.")],
      name: [required("Bitte einen Kartennamen eingeben."), maxLen(100)],
      rarity: [required("Bitte eine Seltenheit wählen.")],
      image: [required("Bitte ein Bild auswählen.")],
    },
  );
  const rv = useValidation(
    { game: reqGame },
    { game: [required("Bitte den Namen des gewünschten Spiels angeben."), maxLen(80)] },
  );

  const rarities = me?.rarities ?? [];
  const rarIndex = useMemo(
    () => Object.fromEntries(rarities.map((r, i) => [r.key, i])),
    [rarities]
  );

  if (loading || !data) return <Spinner />;
  const canEdit = data.can_edit;

  const grouped = (() => {
    const cards = [...data.cards];
    if (sort === "rarity") {
      const by: Record<string, Card[]> = {};
      cards.forEach((c) => (by[c.rarity] ??= []).push(c));
      return rarities
        .filter((r) => by[r.key]?.length)
        .map((r) => ({
          key: r.key,
          label: r.label,
          color: r.color,
          items: by[r.key].sort((a, b) => a.name.localeCompare(b.name)),
        }));
    }
    const by: Record<string, Card[]> = {};
    cards.forEach((c) => (by[c.game || ""] ??= []).push(c));
    return Object.keys(by)
      .sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)))
      .map((g) => ({
        key: g || "__none",
        label: g || "Ohne Spiel",
        color: null as string | null,
        items: by[g].sort(
          (a, b) => (rarIndex[a.rarity] ?? 99) - (rarIndex[b.rarity] ?? 99) || a.name.localeCompare(b.name)
        ),
      }));
  })();

  async function submitUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!v.validateAll() || !file) return;
    const form = new FormData();
    form.append("game", game);
    form.append("name", name);
    form.append("rarity", rarity);
    form.append("image", file);
    setBusy(true);
    try {
      await api.upload(`/api/g/${gid}/cards/add`, form);
      push("ok", "Karte angelegt.");
      setName("");
      setFile(null);
      setUploadKey((k) => k + 1);
      v.reset();
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitRequest(e: React.FormEvent) {
    e.preventDefault();
    if (!rv.validateAll()) return;
    setReqBusy(true);
    try {
      await api.post(`/api/g/${gid}/games/request`, {
        game: reqGame.trim(),
        note: reqNote.trim(),
      });
      push("ok", "Anfrage gesendet — die WebOwner wurden benachrichtigt.");
      setReqGame("");
      setReqNote("");
      setReqSent(true);
    } catch (err) {
      push("err", errText(err));
    } finally {
      setReqBusy(false);
    }
  }

  async function del(card: Card) {
    if (!confirm(`Karte „${card.name}“ löschen?`)) return;
    try {
      await api.post(`/api/g/${gid}/cards/delete`, { card_id: card.id });
      push("ok", "Karte gelöscht.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function rename(card: Card) {
    const n = prompt("Neuer Kartenname:", card.name);
    if (!n?.trim()) return;
    try {
      await api.post(`/api/g/${gid}/cards/rename`, { card_id: card.id, newname: n.trim() });
      push("ok", "Kartenname geändert.");
      reload();
    } catch (err) {
      push("err", errText(err));
    }
  }

  async function replace(card: Card, file: File) {
    const form = new FormData();
    form.append("card_id", card.id);
    form.append("image", file);
    const tid = push("loading", `Bild von „${card.name}" wird ersetzt…`);
    try {
      await api.upload(`/api/g/${gid}/cards/replace`, form);
      update(tid, "ok", `Bild von „${card.name}" ausgetauscht.`);
      reload();
    } catch (err) {
      update(tid, "err", errText(err));
    }
  }

  return (
    <>
      <PageHeader title="Sammelkarten" subtitle={`${data.cards.length} Karten`} />

      {!canEdit && (
        <>
          <InfoBanner>
            Nur-Ansicht — Karten verwalten ist auf bestimmte Personen beschränkt. Du kannst aber unten
            ein Spiel anfragen.
          </InfoBanner>
          <Panel title="Spiel anfragen">
            {reqSent ? (
              <p className="text-sm text-muted">
                Danke! Deine Anfrage wurde an die WebOwner geschickt.{" "}
                <button className="btn btn-ghost btn-sm" onClick={() => setReqSent(false)}>
                  Noch eines anfragen
                </button>
              </p>
            ) : (
              <form onSubmit={submitRequest} className="grid gap-4">
                <Field label="Gewünschtes Spiel" required error={rv.showError("game")}>
                  <input
                    className="field"
                    value={reqGame}
                    onChange={(e) => setReqGame(e.target.value)}
                    onBlur={rv.blur("game")}
                    maxLength={80}
                    placeholder="z. B. Valorant"
                  />
                </Field>
                <Field label="Notiz (optional)">
                  <textarea
                    className="field"
                    value={reqNote}
                    onChange={(e) => setReqNote(e.target.value)}
                    maxLength={300}
                    rows={3}
                    placeholder="Warum dieses Spiel? Welche Karten wünschst du dir?"
                  />
                </Field>
                <div className="flex justify-end">
                  <button className="btn-primary" disabled={reqBusy || !rv.isValid}>
                    {reqBusy ? "Sendet…" : "Anfrage senden"}
                  </button>
                </div>
              </form>
            )}
          </Panel>
        </>
      )}

      {canEdit && data.games.length === 0 && (
        <Panel title="Neue Karte hochladen">
          <p className="text-sm text-muted">
            Lege zuerst unter <b>Spiele &amp; Channel</b> ein Spiel an — Karten gehören immer zu einem Spiel.
          </p>
        </Panel>
      )}

      {canEdit && data.games.length > 0 && (
        <Panel title="Neue Karte hochladen">
          <form onSubmit={submitUpload} className="grid gap-4 sm:grid-cols-2">
            <Field label="Spiel" required error={v.showError("game")}>
              <select
                className="field"
                value={game}
                onChange={(e) => setGame(e.target.value)}
                onBlur={v.blur("game")}
              >
                <option value="">— wählen —</option>
                {data.games.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Kartenname" required error={v.showError("name")}>
              <input
                className="field"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={v.blur("name")}
                maxLength={100}
                placeholder="z. B. Goblin Späher"
              />
            </Field>
            <Field label="Seltenheit" required error={v.showError("rarity")} className="sm:col-span-2">
              <select
                className="field"
                value={rarity}
                onChange={(e) => setRarity(e.target.value)}
                onBlur={v.blur("rarity")}
              >
                <option value="">— wählen —</option>
                {rarities.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field error={v.showError("image")} className="sm:col-span-2">
              <FileUpload key={uploadKey} onChange={(files) => setFile(files[files.length - 1] ?? null)} />
            </Field>
            <div className="flex justify-end sm:col-span-2">
              <button className="btn-primary" disabled={busy || !v.isValid}>
                {busy ? "Lädt…" : "Karte anlegen"}
              </button>
            </div>
          </form>
        </Panel>
      )}

      {/* Sortier-Umschalter */}
      <div className="mb-4 mt-1 flex items-center gap-3">
        <span className="eyebrow">Sortierung</span>
        <div className="seg">
          {(["game", "rarity"] as const).map((k) => (
            <button key={k} data-on={sort === k} onClick={() => setSort(k)}>
              {k === "game" ? "Nach Spiel" : "Nach Seltenheit"}
            </button>
          ))}
        </div>
      </div>

      {grouped.length === 0 && (
        <div className="mt-4">
          <EmptyState>
            Noch keine Karten — {canEdit ? "lade oben deine erste hoch!" : "es wurden noch keine angelegt."}
          </EmptyState>
        </div>
      )}

      {grouped.map((sec) => (
        <div key={sec.key} className="mt-7">
          <div className="group-head">
            <span className="gh-icon">
              {sec.color ? (
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: sec.color }} />
              ) : (
                <Icon name="gamepad" size={16} />
              )}
            </span>
            <h3>{sec.label}</h3>
            <span className="count">{sec.items.length}</span>
            <span className="rule" />
          </div>
          <div className="card-grid">
            {sec.items.map((c, i) => (
              <CardTile
                key={c.id}
                card={c}
                index={i}
                onDelete={canEdit ? del : undefined}
                onRename={canEdit ? rename : undefined}
                onReplace={canEdit ? replace : undefined}
              />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
