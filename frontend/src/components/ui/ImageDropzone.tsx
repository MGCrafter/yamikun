import { useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Icon } from "../Icon";
import { cn } from "../../lib/utils";

/**
 * Moderne Glassmorphism-Upload-Zone für ein einzelnes Bild/Banner.
 * Zeigt bei vorhandenem Bild eine Preview mit Ersetzen/Entfernen, sonst eine
 * Drag-&-Drop-Zone mit Hover-/Drag-Glow.
 */
export function ImageDropzone({
  imageUrl,
  busy,
  onFile,
  onRemove,
  label = "Bild",
  aspect = "aspect-[16/6]",
}: {
  imageUrl: string | null;
  busy?: boolean;
  onFile: (file: File) => void;
  onRemove: () => void;
  /** Bezeichnung des Bildes, z.B. "Banner", "Avatar", "Bild". */
  label?: string;
  /** Tailwind-Aspect-Ratio der Vorschau (z.B. "aspect-square"). */
  aspect?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  const pick = (f: File | null) => {
    if (f && f.type.startsWith("image/")) onFile(f);
  };

  if (imageUrl) {
    return (
      <div className="group relative overflow-hidden rounded-md border border-border bg-surface shadow-glow">
        <div className={`${aspect} w-full overflow-hidden`}>
          <img
            src={imageUrl}
            alt={label}
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
          />
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
        {busy && (
          <div className="absolute inset-0 grid place-items-center bg-black/40 backdrop-blur-sm">
            <div className="h-7 w-7 animate-spin-slow rounded-full border-2 border-white/20 border-t-accent" />
          </div>
        )}
        <div className="absolute bottom-3 right-3 flex gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="btn-ghost px-3 py-1.5 text-[0.82rem]"
          >
            <Icon name="upload" size={15} /> Ersetzen
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="btn px-3 py-1.5 text-[0.82rem] border border-danger/40 bg-danger/10 text-[#ffb4b4] hover:bg-danger/20"
          >
            <Icon name="trash" size={15} /> Entfernen
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
      </div>
    );
  }

  return (
    <motion.div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        pick(e.dataTransfer.files?.[0] ?? null);
      }}
      animate={drag ? { scale: 1.01 } : { scale: 1 }}
      className={cn(
        "relative flex cursor-pointer flex-col items-center justify-center gap-3 rounded-md border-[1.6px] border-dashed px-6 py-12 text-center transition-all duration-300",
        drag
          ? "border-accent/60 bg-[var(--accent-soft)]"
          : "border-border-strong bg-inset hover:border-accent/55 hover:bg-[var(--accent-soft)]"
      )}
    >
      <motion.div
        animate={drag ? { y: -4, scale: 1.12 } : { y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 300, damping: 18 }}
        className="grid h-14 w-14 place-items-center rounded-[14px] border border-border bg-surface-2 text-accent"
      >
        <Icon name="upload" size={24} className="relative" />
      </motion.div>
      <AnimatePresence mode="wait">
        <motion.div
          key={drag ? "drop" : "idle"}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
        >
          <div className="font-semibold text-txt">
            {drag ? "Loslassen zum Hochladen" : `${label} hierher ziehen`}
          </div>
          <div className="mt-1 text-[0.82rem] text-muted">
            oder klicken · PNG · JPG · GIF · WebP · max. 70 MB
          </div>
        </motion.div>
      </AnimatePresence>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />
    </motion.div>
  );
}
