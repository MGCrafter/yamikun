import { useEffect, useRef } from "react";
import { Field } from "./ui/Field";

export type AutoMessage = {
  id: string; name: string; text: string; enabled: boolean;
  interval_minutes: number; min_messages: number; live_only: boolean;
};

export function TwitchAutoMessages({ messages, botName, onChange }: {
  messages: AutoMessage[]; botName: string; onChange: (messages: AutoMessage[]) => void;
}) {
  const focusAfterEdit = useRef<string | null>(null);
  useEffect(() => {
    if (focusAfterEdit.current) {
      document.getElementById(focusAfterEdit.current)?.focus();
      focusAfterEdit.current = null;
    }
  }, [messages.length]);

  function update(id: string, patch: Partial<AutoMessage>) {
    onChange(messages.map(message => message.id === id ? { ...message, ...patch } : message));
  }

  function add() {
    const id = crypto.randomUUID();
    focusAfterEdit.current = `auto-name-${id}`;
    onChange([...messages, { id, name: `Nachricht ${messages.length + 1}`, text: "", enabled: true,
      interval_minutes: 15, min_messages: 5, live_only: true }]);
  }

  function remove(id: string) {
    const remaining = messages.filter(message => message.id !== id);
    const next = remaining[Math.min(messages.findIndex(message => message.id === id), remaining.length - 1)];
    focusAfterEdit.current = next ? `auto-name-${next.id}` : "auto-message-add";
    onChange(remaining);
  }

  return <div className="space-y-5 [&_.field-hint]:text-muted">
    <p className="text-sm leading-relaxed text-muted">Discord-Link, Chat-Regeln oder ein kleiner Reminder: Yami sendet deine Texte regelmäßig. Jede Nachricht hat ihren eigenen Timer. Änderungen werden mit deinen Einstellungen gespeichert.</p>
    {messages.length === 0 && <div className="rounded-xl border border-dashed border-line p-5">
      <p className="font-semibold">Dein erster Chat-Reminder</p>
      <p className="mt-2 text-sm leading-relaxed text-muted">Zum Beispiel alle 15 Minuten auf deinen Discord hinweisen — und erst, wenn im Chat wieder etwas los war.</p>
    </div>}
    {messages.map((message, index) => <div key={message.id} className="min-w-0 space-y-4 rounded-xl border border-line p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Nachricht {index + 1}</h3>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <span>{message.enabled ? "Aktiviert" : "Pausiert"}</span>
            <span className="switch shrink-0"><input type="checkbox" aria-label={`Nachricht ${index + 1} aktivieren`} checked={message.enabled} onChange={e => update(message.id, { enabled: e.target.checked })} /><span className="track pointer-events-none" /><span className="thumb pointer-events-none" /></span>
          </label>
          <button type="button" className="btn btn-ghost min-h-11" aria-label={`Nachricht ${index + 1} entfernen`} onClick={() => remove(message.id)}>Entfernen</button>
        </div>
      </div>
      <Field label="Name" htmlFor={`auto-name-${message.id}`} hint="Nur für deine Übersicht, erscheint nicht im Chat.">
        <input id={`auto-name-${message.id}`} className="field" required maxLength={60} value={message.name} onChange={e => update(message.id, { name: e.target.value })} />
      </Field>
      <Field label="Nachricht im Chat" htmlFor={`auto-text-${message.id}`} hint={`${message.text.length}/500 Zeichen. Text und Links werden genau so gesendet.`}>
        <textarea id={`auto-text-${message.id}`} className="field" rows={3} required maxLength={500} placeholder="Du möchtest auch nach dem Stream dabei sein? Unser Discord: https://…" value={message.text} onChange={e => update(message.id, { text: e.target.value.replace(/[\r\n\t]+/g, " ") })} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Intervall (Minuten)" htmlFor={`auto-interval-${message.id}`} hint="1–1.440 Minuten zwischen Wiederholungen.">
          <input id={`auto-interval-${message.id}`} className="field" type="number" required min={1} max={1440} value={message.interval_minutes} onChange={e => update(message.id, { interval_minutes: Number(e.target.value) })} />
        </Field>
        <Field label="Mindestens Chatnachrichten" htmlFor={`auto-min-${message.id}`} hint="Neue Nachrichten seit dem letzten Versandversuch. 0 = ohne Mindestaktivität.">
          <input id={`auto-min-${message.id}`} className="field" type="number" required min={0} max={1000} value={message.min_messages} onChange={e => update(message.id, { min_messages: Number(e.target.value) })} />
        </Field>
      </div>
      <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 text-sm">
        <span><span className="block font-semibold">Nur senden, wenn ich live bin</span><span className="mt-1 block text-muted">Offline bleibt diese Nachricht pausiert.</span></span>
        <span className="switch shrink-0"><input type="checkbox" aria-label={`Nachricht ${index + 1} nur live senden`} checked={message.live_only} onChange={e => update(message.id, { live_only: e.target.checked })} /><span className="track pointer-events-none" /><span className="thumb pointer-events-none" /></span>
      </label>
      <div className="border-t border-line pt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Chat-Vorschau</p>
        <p className="break-words text-sm leading-relaxed [overflow-wrap:anywhere]"><span className="twitch-bot-tag">BOT</span> <strong className="text-violet">{botName}:</strong> {message.text.trim() || <span className="text-muted">Deine Nachricht erscheint hier.</span>}</p>
      </div>
    </div>)}
    <div className="flex flex-wrap items-center gap-3">
      <button id="auto-message-add" type="button" className="btn btn-ghost min-h-11" disabled={messages.length >= 20} onClick={add}>Nachricht hinzufügen</button>
      <span className="text-sm text-muted" role="status">{messages.length}/20 Nachrichten</span>
    </div>
    <p className="text-sm leading-relaxed text-muted">Intervall und Mindestaktivität müssen beide erreicht sein. Der erste Timer startet beim Speichern. Zwischen Autonachrichten liegt mindestens eine Minute; „Bot pausieren“ stoppt alle.</p>
  </div>;
}
