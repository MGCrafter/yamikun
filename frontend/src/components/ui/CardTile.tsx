import { useRef } from "react";
import type { Card } from "../../lib/api";
import { Icon } from "../Icon";

// Dezente Holo-Stärke je Seltenheit. Die Karte soll beim Hover glänzen,
// aber das eigentliche Kartenbild bleibt immer klar erkennbar.
const HOLO: Record<string, number> = {
  common: 0.1,
  uncommon: 0.13,
  rare: 0.16,
  epic: 0.19,
  legendary: 0.23,
  mythic: 0.28,
};

// TCG-Karte mit Holo-Foil, Pointer-Glare und 3D-Tilt. Eigene Bilder + Hover-Aktionen.
export function CardTile({
  card,
  index = 0,
  onDelete,
  onRename,
  onReplace,
}: {
  card: Card;
  index?: number;
  onDelete?: (card: Card) => void;
  onRename?: (card: Card) => void;
  onReplace?: (card: Card, file: File) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const ref = useRef<HTMLElement>(null);

  function onMove(e: React.MouseEvent) {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--mx", `${(px * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(py * 100).toFixed(1)}%`);
    const rx = (0.5 - py) * 4;
    const ry = (px - 0.5) * 5;
    el.style.transform = `translateY(-4px) perspective(700px) rotateX(${rx}deg) rotateY(${ry}deg)`;
  }
  function onLeave() {
    const el = ref.current;
    if (el) el.style.transform = "";
  }

  const hasActions = onRename || onDelete || onReplace;
  const initial = card.name.replace(/[^A-Za-z0-9]/g, "").slice(0, 1).toUpperCase() || "?";

  return (
    <article
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={`card rar-${card.rarity} rise`}
      style={{
        ["--rc" as string]: card.color,
        ["--holo-strength" as string]: HOLO[card.rarity] ?? 0.16,
        animationDelay: `${Math.min(index * 0.03, 0.4)}s`,
        transformStyle: "preserve-3d",
      }}
    >
      <div className="card-art">
        {card.url ? (
          <img src={card.url} loading="lazy" alt="" />
        ) : (
          <div className="card-sigil">
            <span className="glyph" />
            <span className="mark">{initial}</span>
          </div>
        )}
        <div className="card-holo" />
        <div className="card-holo sheen2" />
        <div className="card-glare" />
        {!card.url && <span className="card-tag">art · platzhalter</span>}
        <span className="rar-badge">{card.rarity_label}</span>

        {hasActions && (
          <div className="absolute right-2.5 top-2.5 z-[6] flex gap-1.5 opacity-0 transition group-hover:opacity-100 [.card:hover_&]:opacity-100">
            {onReplace && (
              <>
                <button
                  type="button"
                  title="Bild austauschen"
                  onClick={() => fileRef.current?.click()}
                  className="grid h-7 w-7 place-items-center rounded-lg border border-border-strong bg-bg/70 text-muted backdrop-blur hover:border-accent hover:text-accent"
                >
                  <Icon name="upload" size={14} />
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) onReplace(card, f);
                    e.target.value = "";
                  }}
                />
              </>
            )}
            {onRename && (
              <button
                type="button"
                title="Umbenennen"
                onClick={() => onRename(card)}
                className="grid h-7 w-7 place-items-center rounded-lg border border-border-strong bg-bg/70 text-muted backdrop-blur hover:border-accent hover:text-accent"
              >
                <Icon name="edit" size={14} />
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                title="Löschen"
                onClick={() => onDelete(card)}
                className="grid h-7 w-7 place-items-center rounded-lg border border-border-strong bg-bg/70 text-muted backdrop-blur hover:border-danger hover:text-danger"
              >
                <Icon name="x" size={14} />
              </button>
            )}
          </div>
        )}
      </div>

      <div className="card-meta">
        <div className="card-name">
          <span className="dot" />
          <span className="truncate">{card.name}</span>
        </div>
        <div className="card-sub">
          {card.count != null ? `${card.rarity_label} · ${card.count}×` : card.game || card.rarity_label}
        </div>
      </div>
    </article>
  );
}
