export type Diagnostics = {
  last_received?: number | null; last_sent?: number | null; last_moderated?: number | null;
  last_live_check?: number | null; live?: boolean | number | null; live_error?: string;
  pending: number; pending_timers: number; oldest_age: number;
  failed_24h: number; expired_24h: number; overloaded_24h: number;
  send_error: string; moderation_error: string;
};

const when = (value?: number | null) => value ? new Date(value * 1000).toLocaleString("de-DE") : "Noch nicht bestätigt";

export function TwitchDiagnostics({ data, connection, enabled, prefix }: { data: Diagnostics; connection: string; enabled: boolean; prefix: string }) {
  const entries = [
    ["Chat-Empfang", enabled ? connection : "Pausiert"],
    ["Letzte Chatnachricht empfangen", when(data.last_received)],
    ["Letzte Antwort gesendet", when(data.last_sent)],
    ["Letzte AutoMod-Aktion ausgeführt", when(data.last_moderated)],
    ["Letzte Live-Prüfung", data.last_live_check ? `${when(data.last_live_check)} · ${data.live ? "Live" : "Offline"}` : "Erfolgt bei fälligen Live-Timern"],
  ];
  return <div className="space-y-5 text-sm">
    <p className="text-muted">Empfang und Versand werden getrennt geprüft. Aktualisiert sich etwa alle 15 Sekunden.</p>
    <dl className="space-y-4">{entries.map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd className="mt-1 break-words font-medium">{value}</dd></div>)}</dl>
    <div className="border-t border-line pt-4"><p className="font-semibold">{data.pending} Nachrichten warten</p><p className="mt-1 text-muted">Davon {data.pending_timers} automatische Nachrichten. {data.pending ? `Älteste wartet ${Math.ceil(data.oldest_age)} Sekunden.` : "Die Warteschlange ist leer."}</p></div>
    {(data.send_error || data.moderation_error || data.live_error) && <div className="space-y-3" role="status">{[data.send_error, data.moderation_error, data.live_error].filter(Boolean).map(message => <p key={message} className="twitch-feedback twitch-feedback-error break-words">{message}</p>)}</div>}
    <div className="border-t border-line pt-4"><p className="font-semibold">Letzte 24 Stunden</p><p className="mt-2 text-muted">{data.failed_24h} fehlgeschlagen · {data.expired_24h} abgelaufen · {data.overloaded_24h} wegen Auslastung nicht ausgeführt</p>
      {data.overloaded_24h > 0 && <p className="mt-3 text-muted">Für wegen Auslastung übersprungene Commands wurden keine Coins gebucht. Ein höherer Cooldown kann den Chat entlasten.</p>}
      {data.expired_24h > 0 && <p className="mt-3 text-muted">Abgelaufene Antworten können zu bereits gebuchten Spielen gehören. Mit {prefix}coins lässt sich das Guthaben prüfen.</p>}
    </div>
  </div>;
}
