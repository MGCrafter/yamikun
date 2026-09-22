import { useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Icon } from "../Icon";

// Schlichte Artwork-Dropzone im Panel-Design. Liefert die zuletzt gewählte Datei
// über onChange (gleiche API wie zuvor). Per `key`-Remount lässt sie sich leeren.
export const FileUpload = ({ onChange }: { onChange?: (files: File[]) => void }) => {
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const take = (files: File[]) => {
    const f = files[files.length - 1] ?? null;
    if (f) {
      setFile(f);
      onChange?.([f]);
    }
  };

  const { getRootProps, isDragActive } = useDropzone({
    multiple: false,
    noClick: true,
    accept: { "image/*": [] },
    onDrop: take,
  });

  return (
    <div
      {...getRootProps()}
      onClick={() => inputRef.current?.click()}
      className={`dropzone cursor-pointer ${isDragActive ? "drag" : ""} ${file ? "has-file" : ""}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => take(Array.from(e.target.files || []))}
      />
      <div>
        <div className="dz-icon">
          <Icon name="upload" size={22} />
        </div>
        {file ? (
          <>
            <div className="font-bold">{file.name}</div>
            <div className="mt-1 text-[13.5px] text-faint">
              {(file.size / (1024 * 1024)).toFixed(2)} MB · zum Ersetzen klicken
            </div>
          </>
        ) : (
          <>
            <div className="font-bold">Artwork hochladen</div>
            <div className="mt-1 text-[13.5px] text-faint">Bild hierher ziehen oder klicken</div>
          </>
        )}
      </div>
    </div>
  );
};
