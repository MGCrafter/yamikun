import { useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText, type Card } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";
import { CardTile } from "../components/ui/CardTile";
import { FileUpload } from "../components/ui/file-upload";
import { PageHeader, Panel, EmptyState, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, maxLen } from "../lib/validators";

type YamiData = { can_edit: boolean; cards: Card[] };

export default function Yami() {
  const { gid } = useParams();
  const { me } = useAuth();
  const { push, update } = useToast();
  const { data, loading, reload } = useApiData<YamiData>(`/api/g/${gid}/yami`);
  const [name, setName] = useState("");
  const [rarity, setRarity] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadKey, setUploadKey] = useState(0); // remount -> Upload-Feld nach Erfolg leeren
  const [busy, setBusy] = useState(false);
  const v = useValidation(
    { name, rarity, image: file },
    {
      name: [required("Bitte einen Kartennamen eingeben."), maxLen(100)],
      rarity: [required("Bitte eine Seltenheit wählen.")],
      image: [required("Bitte ein Bild auswählen.")],
    },
  );

  const rarities = me?.rarities ?? [];
  if (loading || !data) return <Spinner />;
  const canEdit = data.can_edit;

  const grouped = rarities
    .map((r) => ({ ...r, items: data.cards.filter((c) => c.rarity === r.key) }))
    .filter((r) => r.items.length);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!v.validateAll() || !file) return;
    const form = new FormData();
    form.append("name", name);
    form.append("rarity", rarity);
    form.append("image", file);
    setBusy(true);
    try {
      await api.upload(`/api/g/${gid}/yami/add`, form);
      push("ok", "Yami-Karte angelegt.");
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

  async function del(card: Card) {
    if (!confirm(`Yami-Karte „${card.name}“ löschen?`)) return;
    try {
      await api.post(`/api/g/${gid}/yami/delete`, { card_id: card.id });
      push("ok", "Yami-Karte gelöscht.");
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
      await api.upload(`/api/g/${gid}/yami/replace`, form);
      update(tid, "ok", `Bild von „${card.name}" ausgetauscht.`);
      reload();
    } catch (err) {
      update(tid, "err", errText(err));
    }
  }

  return (
    <>
      <PageHeader title="Yami-Karten" subtitle={`${data.cards.length} Karten`} />
      <InfoBanner>Yami-Karten sind serverübergreifend (global) — Änderungen gelten auf allen Servern.</InfoBanner>

      {!canEdit ? (
        <InfoBanner>Nur-Ansicht — Verwalten ist auf bestimmte Personen beschränkt.</InfoBanner>
      ) : (
        <Panel title="Neue Yami-Karte hochladen">
          <p className="mb-4 text-sm text-muted">
            Yami-Karten kommen über Booster-Packs (mit Coins gekauft) ins Spiel — getrennt von den
            erspielten Sammelkarten.
          </p>
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
            <Field label="Kartenname" required error={v.showError("name")}>
              <input
                className="field"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={v.blur("name")}
                maxLength={100}
                placeholder="z. B. Yami Königin"
              />
            </Field>
            <Field label="Seltenheit" required error={v.showError("rarity")}>
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

      {grouped.length === 0 && (
        <EmptyState>
          Noch keine Yami-Karten — {canEdit ? "lade oben deine erste hoch!" : "es wurden noch keine angelegt."}
        </EmptyState>
      )}

      {grouped.map((sec) => (
        <div key={sec.key} className="mt-7">
          <div className="group-head">
            <span className="gh-icon">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: sec.color }} />
            </span>
            <h3>{sec.label}</h3>
            <span className="count">{sec.items.length}</span>
            <span className="rule" />
          </div>
          <div className="card-grid">
            {sec.items.map((c, i) => (
              <CardTile key={c.id} card={c} index={i} onDelete={canEdit ? del : undefined} onReplace={canEdit ? replace : undefined} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
