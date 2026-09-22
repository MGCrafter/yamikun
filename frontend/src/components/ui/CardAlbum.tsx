import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { Card } from "../../lib/api";

export type AlbumGame = {
  game: string;
  cards: Card[];
  fusable: Record<string, number>;
  booster_count: number;
};

type AlbumPage = {
  key: string;
  game: AlbumGame;
  cards: Card[];
  part: number;
  parts: number;
};

const PAGE_SIZE = 6;

export function CardAlbum({
  games,
  shards,
  boosterCost,
  dismantleRewards,
  busy,
  onDismantle,
  onExchange,
}: {
  games: AlbumGame[];
  shards: number;
  boosterCost: number;
  dismantleRewards: Record<string, number>;
  busy: string | null;
  onDismantle: (card: Card) => Promise<boolean>;
  onExchange: (game: AlbumGame) => Promise<boolean>;
}) {
  const pages = useMemo<AlbumPage[]>(
    () => games.flatMap((game) => {
      const parts = Math.max(1, Math.ceil(game.cards.length / PAGE_SIZE));
      return Array.from({ length: parts }, (_, part) => ({
        key: `${game.game}:${part}`,
        game,
        cards: game.cards.slice(part * PAGE_SIZE, (part + 1) * PAGE_SIZE),
        part,
        parts,
      }));
    }),
    [games],
  );
  const [singlePage, setSinglePage] = useState(false);
  const spreads = Math.max(1, singlePage ? pages.length : Math.ceil(pages.length / 2));
  const [spread, setSpread] = useState(0);
  const [turning, setTurning] = useState<"next" | "prev" | null>(null);
  const [selected, setSelected] = useState<Card | null>(null);
  const [exchangeOpen, setExchangeOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 780px)");
    const sync = () => setSinglePage(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  useEffect(() => setSpread((n) => Math.min(n, spreads - 1)), [spreads]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelected(null);
        setExchangeOpen(false);
      } else if (event.key === "ArrowRight" && !selected && !exchangeOpen) {
        turn(1);
      } else if (event.key === "ArrowLeft" && !selected && !exchangeOpen) {
        turn(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const total = games.reduce((sum, game) => sum + game.cards.length, 0);
  const discovered = games.reduce(
    (sum, game) => sum + game.cards.filter((card) => (card.count ?? 0) > 0).length,
    0,
  );
  const percentage = total ? Math.round((discovered / total) * 100) : 0;
  const leftIndex = singlePage ? spread : spread * 2;
  const rightIndex = leftIndex + 1;
  const left = pages[leftIndex];
  const right = singlePage ? undefined : pages[rightIndex];

  function turn(direction: 1 | -1) {
    if (turning || spreads <= 1) return;
    const next = (spread + direction + spreads) % spreads;
    setTurning(direction === 1 ? "next" : "prev");
    window.setTimeout(() => setSpread(next), 280);
    window.setTimeout(() => setTurning(null), 620);
  }

  async function dismantle() {
    if (!selected) return;
    if (await onDismantle(selected)) setSelected(null);
  }

  return (
    <section className="album-shell" aria-label="Animiertes Spielkarten-Sammelalbum">
      <div className="album-heading">
        <div>
          <div className="album-kicker">Deine Spiel-Sammelkarten</div>
          <h2>Das Archiv der <em>Welten</em></h2>
          <p>Vervollständige deine Spiele-Sets und verwandle doppelte Karten in Arkansplitter.</p>
        </div>
        <div className="album-resources">
          <div className="album-resource"><span>✦</span><b>{shards.toLocaleString("de-DE")}</b><small>Arkansplitter</small></div>
          <div className="album-resource"><span>◈</span><b>{games.reduce((n, g) => n + g.booster_count, 0)}</b><small>Spiel-Booster</small></div>
        </div>
      </div>

      <div className="album-tools">
        <button className="album-exchange-button" onClick={() => setExchangeOpen(true)}>✦ Booster eintauschen</button>
        <div className="album-progress">
          <div><span>Gesamtsammlung</span><b>{discovered} / {total} · {percentage}%</b></div>
          <div className="album-progress-track"><i style={{ width: `${percentage}%` }} /></div>
        </div>
      </div>

      {pages.length === 0 ? (
        <div className="album-empty">Noch wurden keine Spiel-Sammelkarten angelegt.</div>
      ) : (
        <div className="album-stage">
          <div className="album-aura" />
          <div className="album-book">
            <div className="album-cover-edge" />
            <button className="album-turn album-prev" onClick={() => turn(-1)} aria-label="Vorherige Albumseiten">←</button>
            <button className="album-turn album-next" onClick={() => turn(1)} aria-label="Nächste Albumseiten">→</button>
            {turning && <div className={`album-flip album-flip-${turning}`}><div /><div /></div>}
            <div className={`album-spread ${singlePage ? "album-single-page" : ""}`}>
              <AlbumLeaf page={left} side="left" pageNumber={leftIndex + 1} onSelect={setSelected} />
              {!singlePage && <AlbumLeaf page={right} side="right" pageNumber={rightIndex + 1} onSelect={setSelected} />}
            </div>
          </div>
          <div className="album-page-indicator">
            {singlePage ? `Seite ${leftIndex + 1}` : `Seiten ${leftIndex + 1}–${Math.min(rightIndex + 1, pages.length)}`} von {pages.length}
          </div>
        </div>
      )}

      {selected && (
        <div className="album-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setSelected(null)}>
          <div className="album-card-dialog" role="dialog" aria-modal="true" aria-label={selected.name}>
            <div className="album-dialog-preview">
              {selected.url ? (
                <div className="album-dialog-image">
                  <span>{selected.name.slice(0, 1)}</span>
                  <img src={selected.url} alt={selected.name} onError={(e) => e.currentTarget.remove()} />
                </div>
              ) : <span>{selected.name.slice(0, 1)}</span>}
            </div>
            <div className="album-dialog-body">
              <button className="album-close" onClick={() => setSelected(null)} aria-label="Schließen">×</button>
              <div className="album-kicker" style={{ color: selected.color }}>{selected.rarity_label} · Spielkarte</div>
              <h3>{selected.name}</h3>
              <p>
                {(selected.count ?? 0) > 1
                  ? "Diese Karte besitzt du doppelt. Das zusätzliche Exemplar kann sicher in Arkansplitter zerlegt werden."
                  : "Dieses Exemplar bleibt sicher in deinem Album. Erst ein Duplikat kann zerlegt werden."}
              </p>
              <div className="album-reward-grid">
                <div><small>Im Album</small><b>{Math.max(1, (selected.count ?? 1) - ((selected.count ?? 0) > 1 ? 1 : 0))} Exemplar{(selected.count ?? 1) > 2 ? "e" : ""} bleibt</b></div>
                <div><small>Du erhältst</small><b>✦ {dismantleRewards[selected.rarity] ?? 0} Splitter</b></div>
              </div>
              <div className="album-dialog-actions">
                <button className="btn" onClick={() => setSelected(null)}>Behalten</button>
                <button
                  className="album-dismantle"
                  disabled={(selected.count ?? 0) <= 1 || busy === `dismantle:${selected.id}`}
                  onClick={dismantle}
                >
                  {busy === `dismantle:${selected.id}` ? "Wird zerlegt…" : "✦ Duplikat zerlegen"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {exchangeOpen && (
        <div className="album-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setExchangeOpen(false)}>
          <div className="album-exchange" role="dialog" aria-modal="true" aria-label="Booster-Tauschkammer">
            <button className="album-close" onClick={() => setExchangeOpen(false)} aria-label="Schließen">×</button>
            <div className="album-kicker">Tauschkammer</div>
            <h3>Arkansplitter gegen Spiel-Booster</h3>
            <p>Der Booster landet im vorhandenen Booster-Inventar und kann auch über <code>/booster opengame</code> geöffnet werden.</p>
            <div className="album-booster-grid">
              {games.filter((game) => game.game !== "Ohne Spiel").map((game, index) => (
                <article className="album-booster" key={game.game} style={{ ["--pack-hue" as string]: `${268 + (index % 4) * 34}` } as CSSProperties}>
                  <div className="album-pack"><span>Y</span><small>{game.game}</small></div>
                  <h4>{game.game}</h4>
                  <p>{game.cards.length} mögliche Karten · {game.booster_count} im Inventar</p>
                  <div><b>✦ {boosterCost.toLocaleString("de-DE")}</b><button
                    disabled={shards < boosterCost || busy === `exchange:${game.game}`}
                    onClick={() => onExchange(game)}
                  >{busy === `exchange:${game.game}` ? "Tauscht…" : "Eintauschen"}</button></div>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function AlbumLeaf({ page, side, pageNumber, onSelect }: {
  page?: AlbumPage;
  side: "left" | "right";
  pageNumber: number;
  onSelect: (card: Card) => void;
}) {
  if (!page) return <div className={`album-leaf album-${side} album-blank`}><span>✦</span></div>;
  const owned = page.game.cards.filter((card) => (card.count ?? 0) > 0).length;
  return (
    <div className={`album-leaf album-${side}`}>
      <div className="album-leaf-head">
        <span>❖</span>
        <h3>{page.game.game}</h3>
        {page.parts > 1 && <small>Blatt {page.part + 1}/{page.parts}</small>}
        <b>{owned} / {page.game.cards.length}</b>
      </div>
      <div className="album-card-slots">
        {Array.from({ length: PAGE_SIZE }, (_, index) => {
          const card = page.cards[index];
          if (!card) return <div className="album-slot album-unused" key={`unused:${index}`} />;
          const has = (card.count ?? 0) > 0;
          return (
            <button
              className={`album-slot ${has ? "album-owned" : "album-locked"}`}
              key={card.id}
              disabled={!has}
              onClick={() => has && onSelect(card)}
              style={{ ["--rarity" as string]: card.color } as CSSProperties}
              aria-label={has ? `${card.name}, ${card.count} Exemplare` : "Noch nicht entdeckt"}
            >
              {has ? (
                <>
                  <div className="album-card-art">
                    <span>{card.name.slice(0, 1)}</span>
                    {card.url && <img src={card.url} alt="" loading="lazy" onError={(e) => e.currentTarget.remove()} />}
                    <i />
                  </div>
                  {(card.count ?? 0) > 1 && <span className="album-quantity">×{card.count}</span>}
                  <div className="album-card-caption"><b>{card.name}</b><small>{card.rarity_label}</small></div>
                </>
              ) : (
                <><span className="album-lock-sigil">✦</span><small>Noch nicht entdeckt</small></>
              )}
            </button>
          );
        })}
      </div>
      <span className="album-page-number">{String(pageNumber).padStart(2, "0")}</span>
    </div>
  );
}
