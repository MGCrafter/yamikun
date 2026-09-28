import { useEffect, useRef } from "react";
import { Field } from "./ui/Field";

export type CustomCommand = {
  id: string; name: string; response: string; enabled: boolean; aliases: string[];
  user_level: "everyone" | "subscriber" | "vip" | "moderator" | "broadcaster";
  cooldown: number; user_cooldown: number;
};

export function commandErrors(commands: CustomCommand[], reserved: string[]) {
  const used = new Set(reserved);
  return commands.map(command => {
    let error = "";
    for (const trigger of [command.name, ...command.aliases]) {
      const name = trigger.trim().toLowerCase();
      if (!/^[a-z0-9][a-z0-9_]{0,24}$/.test(name)) error = "Namen brauchen 1–25 Buchstaben, Ziffern oder Unterstriche; ohne Präfix.";
      else if (used.has(name)) error = `„${name}“ ist bereits vergeben oder ein Standard-Command.`;
      used.add(name);
    }
    if (command.aliases.length > 5) error = "Maximal fünf Aliasse pro Command.";
    if (!command.response.trim()) error ||= "Bitte eine Antwort eingeben.";
    return error;
  });
}

export function TwitchCustomCommands({ commands, prefix, channel, botName, reserved, onChange }: {
  commands: CustomCommand[]; prefix: string; channel: string; botName: string; reserved: string[];
  onChange: (commands: CustomCommand[]) => void;
}) {
  const focus = useRef<string | null>(null);
  useEffect(() => {
    if (focus.current) { document.getElementById(focus.current)?.focus(); focus.current = null; }
  }, [commands.length]);
  const errors = commandErrors(commands, reserved);
  function update(id: string, patch: Partial<CustomCommand>) {
    onChange(commands.map(command => command.id === id ? { ...command, ...patch } : command));
  }
  function add() {
    const id = crypto.randomUUID();
    focus.current = `command-name-${id}`;
    onChange([...commands, { id, name: "", response: "", enabled: true, aliases: [],
      user_level: "everyone", cooldown: 10, user_cooldown: 30 }]);
  }
  function remove(id: string) {
    const remaining = commands.filter(command => command.id !== id);
    const next = remaining[Math.min(commands.findIndex(command => command.id === id), remaining.length - 1)];
    focus.current = next ? `command-name-${next.id}` : "custom-command-add";
    onChange(remaining);
  }
  return <div className="space-y-5 [&_.field-hint]:text-muted">
    <p className="text-sm leading-relaxed text-muted">Deine Antworten auf {prefix}discord, {prefix}socials oder {prefix}regeln. Jeder Command kann eigene Rechte und Wartezeiten haben. Änderungen werden mit deinen Einstellungen gespeichert.</p>
    {!commands.length && <div className="rounded-xl border border-dashed border-line p-5"><p className="font-semibold">Was soll Yami für dich beantworten?</p><p className="mt-2 text-sm text-muted">Lege zum Beispiel „discord“ an und hinterlege deinen Einladungslink als Antwort.</p></div>}
    {commands.map((command, index) => {
      const example: Record<string, string> = { user: "@luna", channel, target: "@neko", args: "@neko" };
      const preview = command.response.replace(/\{(user|channel|target|args)\}/g, (_, key: string) => example[key]).slice(0, 500);
      return <div key={command.id} className="min-w-0 space-y-4 rounded-xl border border-line p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="break-all font-semibold">{command.name ? `${prefix}${command.name}` : `Command ${index + 1}`}</h3>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm"><span>{command.enabled ? "Aktiviert" : "Pausiert"}</span><span className="switch shrink-0"><input type="checkbox" aria-label={`Command ${index + 1} aktivieren`} checked={command.enabled} onChange={e => update(command.id, { enabled: e.target.checked })} /><span className="track pointer-events-none" /><span className="thumb pointer-events-none" /></span></label>
            <button type="button" className="btn btn-ghost min-h-11" aria-label={`Command ${index + 1} entfernen`} onClick={() => remove(command.id)}>Entfernen</button>
          </div>
        </div>
        <Field label="Command-Name" htmlFor={`command-name-${command.id}`} hint={`Ohne ${prefix} eingeben. Standard-Commands bleiben reserviert.`}>
          <input id={`command-name-${command.id}`} className="field" required maxLength={25} pattern="[a-z0-9][a-z0-9_]{0,24}" value={command.name} placeholder="discord" aria-describedby={errors[index] ? `command-error-${command.id}` : undefined} aria-invalid={Boolean(errors[index])} onChange={e => update(command.id, { name: e.target.value.toLowerCase() })} />
        </Field>
        <Field label="Antwort im Chat" htmlFor={`command-response-${command.id}`} hint={`${command.response.length}/500 Zeichen. Platzhalter: {user}, {channel}, {target}, {args}.`}>
          <textarea id={`command-response-${command.id}`} className="field" required rows={3} maxLength={500} value={command.response} placeholder="Komm auf unseren Discord: https://…" onChange={e => update(command.id, { response: e.target.value.replace(/[\r\n\t]+/g, " ") })} />
        </Field>
        <Field label="Aliasse (optional)" htmlFor={`command-aliases-${command.id}`} hint="Weitere Namen für dieselbe Antwort, mit Komma trennen. Maximal fünf; sie teilen die Cooldowns.">
          <input id={`command-aliases-${command.id}`} className="field" value={command.aliases.join(", ")} placeholder="dc, community" onBlur={() => update(command.id, { aliases: command.aliases.filter(Boolean) })} onChange={e => update(command.id, { aliases: e.target.value ? e.target.value.toLowerCase().split(",").map(name => name.trim()) : [] })} />
        </Field>
        <Field label="Wer darf den Command nutzen?" htmlFor={`command-level-${command.id}`}>
          <select id={`command-level-${command.id}`} className="field" value={command.user_level} onChange={e => update(command.id, { user_level: e.target.value as CustomCommand["user_level"] })}>
            <option value="everyone">Alle Zuschauer</option><option value="subscriber">Abonnenten, VIPs und Moderatoren</option><option value="vip">VIPs und Moderatoren</option><option value="moderator">Moderatoren</option><option value="broadcaster">Nur ich als Streamer</option>
          </select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Channel-Cooldown (Sekunden)" htmlFor={`command-cooldown-${command.id}`} hint="Wartezeit nach jeder Nutzung, für alle. 0–3.600 Sekunden."><input id={`command-cooldown-${command.id}`} className="field" type="number" required min={0} max={3600} value={command.cooldown} onChange={e => update(command.id, { cooldown: Number(e.target.value) })} /></Field>
          <Field label="Persönlicher Cooldown (Sekunden)" htmlFor={`command-user-cooldown-${command.id}`} hint="Zusätzlich pro Zuschauer. 0–86.400 Sekunden."><input id={`command-user-cooldown-${command.id}`} className="field" type="number" required min={0} max={86400} value={command.user_cooldown} onChange={e => update(command.id, { user_cooldown: Number(e.target.value) })} /></Field>
        </div>
        {errors[index] && <p id={`command-error-${command.id}`} className="field-error" role="alert">{errors[index]}</p>}
        <div className="border-t border-line pt-4"><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Beispiel: luna schreibt {prefix}{command.name || "command"} @neko</p><p className="break-words text-sm leading-relaxed [overflow-wrap:anywhere]"><span className="twitch-bot-tag">BOT</span> <strong className="text-violet">{botName}:</strong> {preview || <span className="text-muted">Deine Antwort erscheint hier.</span>}</p></div>
      </div>;
    })}
    <div className="flex flex-wrap items-center gap-3"><button id="custom-command-add" type="button" className="btn btn-ghost min-h-11" disabled={commands.length >= 50} onClick={add}>Command hinzufügen</button><span className="text-sm text-muted" role="status">{commands.length}/50 Commands</span></div>
    <p className="text-sm leading-relaxed text-muted">{`{user} nennt den Zuschauer, {channel} deinen Kanal, {target} die erste genannte Person und {args} den Text nach dem Command. Ohne Ziel wird der Zuschauer selbst genannt. Antworten werden auf 500 Zeichen begrenzt.`}</p>
  </div>;
}
