import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Field } from "../components/ui/Field";
import { TwitchAutoMessages, type AutoMessage } from "../components/TwitchAutoMessages";

type Settings = {
  prefix: string; social_enabled: boolean; gambling_enabled: boolean;
  automod_enabled: boolean; block_links: boolean; block_caps: boolean; block_spam: boolean;
  blocked_words: string[]; timeout_seconds: number; command_cooldown: number;
  max_bet: number; daily_coins: number; auto_messages: AutoMessage[];
};
type Data = {
  authenticated: boolean; configured: boolean; bot_ready: boolean; bot_login: string | null;
  can_setup_bot?: boolean;
  csrf?: string; user?: { id: string; login: string; display_name: string };
  channel?: { enabled: boolean; status: string; error: string; connection_error?: string; settings: Settings };
  commands: { usage: string; description: string }[];
  discord_link?: { id: string; name: string } | null;
  discord_session?: { id: string; name: string } | null;
  leaderboard?: { login: string; coins: number }[];
  moderation_log?: { login: string; reason: string; action: string; created: number; outcome: string }[];
};
const ERRORS: Record<string, string> = {
  state: "Die Anmeldung ist abgelaufen oder gehört zu einem anderen Anmeldeversuch. Bitte starte sie in diesem Browser erneut.",
  denied: "Twitch-Anmeldung abgebrochen. Du kannst es jederzeit erneut versuchen.",
  not_configured: "Die Twitch-Anbindung wird noch eingerichtet.",
  bot_not_ready: "Das Botkonto ist noch nicht verbunden. Bitte später erneut versuchen.",
  wrong_bot_account: "Bitte mit dem vorgesehenen Twitch-Botkonto anmelden.",
  missing_scopes: "Es fehlen Twitch-Berechtigungen. Bitte erneut anmelden und die Freigabe bestätigen.",
  twitch_unavailable: "Twitch ist gerade nicht erreichbar. Bitte versuche es später erneut.",
  invalid_settings: "Bitte prüfe die Eingaben und die angegebenen Grenzen.",
  bad_csrf: "Deine Sitzung ist abgelaufen. Bitte lade die Seite neu.",
  unauthorized: "Bitte melde dich erneut mit Twitch an.",
  discord_login_required: "Bitte melde dich zuerst auch mit Discord an.",
  account_already_linked: "Eines dieser Konten ist bereits verknüpft. Trenne zuerst die bestehende Verbindung.",
  game_in_progress: "Beende zuerst deine offenen Blackjack-Runden und Duellanfragen.",
};
const STATUS: Record<string, string> = {
  connected: "Im Chat verbunden", connecting: "Verbindung wird aufgebaut", disabled: "Bot ist pausiert",
  error: "Verbindung prüfen", reauth: "Erneut anmelden",
};

async function request(path: string, csrf?: string, body?: unknown): Promise<Data> {
  const res = await fetch(`/api/twitch/${path}`, {
    credentials: "same-origin", method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json", "X-CSRF-Token": csrf ?? "" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(ERRORS[payload.error] ?? "Die Anfrage konnte nicht abgeschlossen werden. Bitte erneut versuchen.");
  }
  return res.json();
}

function Section({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><h2 className="mb-5 font-display text-xl font-bold">{title}</h2>{children}</section>;
}

function Toggle({ title, hint, value, onChange }: { title: string; hint: string; value: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-card cursor-pointer gap-4">
    <span><span className="tc-label block">{title}</span><span className="mt-1 block text-sm text-muted">{hint}</span></span>
    <span className="switch shrink-0"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} aria-label={title} /><span className="track" /><span className="thumb" /></span>
  </label>;
}

export default function TwitchChat() {
  const [params] = useSearchParams();
  const [data, setData] = useState<Data | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [words, setWords] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await request("me");
        if (!active) return;
        setData(next);
        setError("");
        if (next.channel) {
          setSettings(current => current ?? next.channel!.settings);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "Verbindung fehlgeschlagen.");
      }
    };
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [retry]);

  useEffect(() => { if (settings) setWords(settings.blocked_words.join("\n")); }, [settings?.blocked_words]);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings(current => current ? { ...current, [key]: value } : null);
    setDirty(true);
    setNotice("");
  }

  async function action(path: string, body: unknown, success: string) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const next = await request(path, data?.csrf, body);
      if (path === "logout") { window.location.assign("/twitch"); return; }
      setData(next);
      if (path === "settings" && next.channel) {
        setSettings(next.channel.settings); setDirty(false);
      }
      setNotice(success);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Aktion fehlgeschlagen.");
    } finally { setBusy(false); }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void action("settings", { enabled: data?.channel?.enabled ?? false, settings: { ...settings, blocked_words: words.split("\n").map(w => w.trim()).filter(Boolean) } }, "Einstellungen gespeichert.");
  }

  const auth = Boolean(data?.authenticated);
  const channel = data?.channel;
  const prefix = settings?.prefix ?? "!";
  const queryError = params.get("error");
  const setupBot = params.get("setup") === "bot";

  return <div className="twitch-page min-h-screen">
    <div className="mx-auto max-w-6xl px-5 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line py-5">
        <Link to="/" className="flex items-center gap-3 font-display text-lg font-bold"><img src="/assets/YamiKun.webp" alt="" className="h-10 w-10 rounded-lg" />Yamikun <span className="twitch-label">Twitch</span></Link>
        <nav aria-label="Twitch-Navigation" className="flex w-full flex-wrap items-center justify-between gap-1 sm:w-auto sm:gap-4">
          <a href="#commands" className="btn btn-ghost">Commands</a>
          <Link to="/" className="btn btn-ghost">Discord</Link>
          {auth && <button className="btn btn-ghost" disabled={busy} onClick={() => void action("logout", {}, "")}>Abmelden</button>}
          <ThemeToggle />
        </nav>
      </header>

      <main className="pb-16">
        <div className="mt-6 space-y-3" aria-live="polite">
          {(error || queryError) && <div className="twitch-feedback twitch-feedback-error" role="alert">{error || ERRORS[queryError!] || "Twitch-Anmeldung fehlgeschlagen. Bitte erneut versuchen."}
            {!data && <button className="btn btn-ghost ml-3" onClick={() => setRetry(v => v + 1)}>Erneut laden</button>}
          </div>}
          {notice && <div className="twitch-feedback" role="status">{notice}</div>}
          {params.get("connected") === "bot" && <div className="twitch-feedback">Botkonto verbunden. Streamer können Yami jetzt hinzufügen.</div>}
        </div>

        {!auth ? <section className="twitch-hero grid items-center gap-12 py-12 lg:grid-cols-[1.15fr_1fr] lg:py-20">
          <div>
            <div className="mb-5 flex items-center gap-2 text-sm font-semibold text-violet"><Icon name="twitch" size={20} /> DEIN CHAT. DEIN YAMI.</div>
            <h1 className="font-display text-5xl font-bold leading-[1.08] tracking-tight sm:text-6xl">Mehr Leben<br />in deinem Chat.</h1>
            <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted">Yami zieht bei dir auf Twitch ein. Gemeinsam spielen, Coins sammeln und Freundschaften schließen — mit AutoMod, der auf deinen Chat aufpasst.</p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              {data?.configured ? <a className="btn-primary px-6 py-3" href={setupBot ? "/twitch/login?bot=1" : "/twitch/login"}><Icon name="twitch" size={20} />{setupBot ? "Botkonto verbinden" : "Mit Twitch anmelden"}</a>
                : <button className="btn-primary px-6 py-3" disabled>{data ? "Twitch wird eingerichtet" : "Verbindung wird geprüft…"}</button>}
              <a href="#commands" className="btn btn-ghost">Commands entdecken <Icon name="arrow" size={17} /></a>
            </div>
            <p className="mt-4 text-sm text-muted">Mit deinem Twitch-Konto anmelden und Yami zu deinem eigenen Channel hinzufügen. Discord ist optional.</p>
          </div>
          <div className="twitch-chat-preview" aria-label="Beispiel eines Twitch-Chats">
            <div className="flex items-center justify-between border-b border-line px-5 py-4"><span className="font-display font-bold">Dein Stream-Chat</span><span className="text-xs text-muted">BEISPIEL</span></div>
            <div className="space-y-5 px-5 py-7 text-sm leading-relaxed sm:text-base">
              <p><span className="font-bold text-violet">luna</span> <span className="text-muted">!hug @neko</span></p>
              <p><span className="twitch-bot-tag">BOT</span> <strong>Yami</strong> <span className="text-muted">@luna umarmt @neko!</span></p>
              <p><span className="font-bold text-violet">neko</span> <span className="text-muted">!coinflip 50 kopf</span></p>
              <p><span className="twitch-bot-tag">BOT</span> <strong>Yami</strong> <span className="text-muted">@neko Kopf · Einsatz 50, Auszahlung 100 · Guthaben 550 Coins.</span></p>
              <div className="mt-6 flex items-center gap-2 border-t border-line pt-5 text-sm text-muted"><Icon name="shield" size={17} />Deine Regeln. Yami kümmert sich.</div>
            </div>
          </div>
        </section> : <section className="flex flex-wrap items-end justify-between gap-6 py-10">
          <div className="min-w-0"><p className="mb-3 font-semibold text-violet">TWITCH / {data?.user?.login}</p><h1 className="break-words font-display text-4xl font-bold sm:text-5xl">Willkommen, {data?.user?.display_name}.</h1><p className="mt-4 text-muted">Hier wohnt Yami in deinem Chat. Du bestimmst die Regeln.</p></div>
          <div className="flex flex-col items-start gap-3 sm:items-end"><span className="twitch-label" role="status">{STATUS[channel?.status ?? "disabled"] ?? "Verbindung prüfen"}</span>
            <a className="btn btn-ghost" href={`https://www.twitch.tv/${data?.user?.login}`} target="_blank" rel="noreferrer">Deinen Channel öffnen <Icon name="arrow" size={16} /></a></div>
        </section>}

        {!auth && <div className="grid gap-5 pb-12 md:grid-cols-3">{[
          { icon: "users", title: "Für deine Community", text: "Hugs, High-Fives, Freundschaften und Heiratsanträge. Kleine Momente, die deinen Chat verbinden." },
          { icon: "coins", title: "Noch eine Runde?", text: "Coinflip, Slots, Roulette und Blackjack — mit virtuellen Coins, Daily-Bonus und Rangliste." },
          { icon: "shield", title: "Dein Chat, deine Regeln", text: "Links, Spam, Caps und gesperrte Begriffe filtern. Nachrichten löschen oder Timeouts vergeben." },
        ].map(item => <div className="border-t border-line pt-6" key={item.title}><Icon name={item.icon} className="mb-4 text-violet" size={24} /><h2 className="font-display text-lg font-bold">{item.title}</h2><p className="mt-2 leading-relaxed text-muted">{item.text}</p></div>)}</div>}

        {auth && channel && settings && <>
          {(!data?.configured || (!data?.bot_ready && !data?.can_setup_bot && !setupBot)) && <div className="twitch-feedback mb-6">Das Botkonto wird noch eingerichtet. Du kannst deine Einstellungen bereits vorbereiten.</div>}
          {channel.error && <div className="twitch-feedback twitch-feedback-error mb-6" role="alert">{channel.error} {(channel.connection_error ?? channel.error) && <a className="underline" href="/twitch/login">Twitch-Freigabe erneuern</a>}</div>}
          {(data?.can_setup_bot || setupBot) && data?.configured && <Section title="Yamis Botkonto" className="mb-6">
            <p className="mb-4 max-w-3xl leading-relaxed text-muted">{data.bot_ready
              ? `Das Botkonto ${data.bot_login ?? "Yami"} ist verbunden. Melde dich anschließend mit deinem Streamer-Konto an, um Yami zu deinem Channel hinzuzufügen.`
              : data.can_setup_bot
                ? `Du bist als ${data.user?.display_name} angemeldet. Dieses Konto ist als Yamis Botkonto vorgesehen. Erteile jetzt einmalig die zusätzliche Freigabe, damit Yami unter diesem Namen in allen angeschlossenen Channels lesen und antworten kann.`
                : "Verbinde hier einmalig das vorgesehene Twitch-Botkonto. Wähle bei Twitch das Botkonto und bestätige die Berechtigungen für Chat-Nachrichten."}</p>
            <a href="/twitch/login?bot=1" className="btn-primary"><Icon name="twitch" size={18} />{data.bot_ready ? "Botkonto-Freigabe erneuern" : "Botkonto verbinden"}</a>
            {!data.bot_ready && <p className="mt-3 text-sm text-muted">Der Button startet die Twitch-Freigabe direkt in diesem Browser. Nach der Bestätigung kannst du Yami mit deinem Streamer-Konto hinzufügen.</p>}
          </Section>}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <form onSubmit={save} className="min-w-0 space-y-6">
              <fieldset disabled={busy} className="min-w-0 space-y-6 disabled:opacity-70">
                <Section title="Yami in deinem Channel">
                  <p className="mb-5 text-muted">{channel.enabled ? `Yami antwortet als ${data?.bot_login ?? "dein Bot"}. Beim Pausieren werden offene Runden abgerechnet.` : "Füge Yami hinzu, damit er auf Commands reagiert und deine aktivierten Chat-Regeln anwendet."}</p>
                  <button type="button" className={channel.enabled ? "btn btn-ghost" : "btn-primary"} disabled={!channel.enabled && (!data?.configured || !data?.bot_ready)} onClick={() => void action("settings", { enabled: !channel.enabled, settings: { ...settings, blocked_words: words.split("\n").map(w => w.trim()).filter(Boolean) } }, channel.enabled ? "Yami ist pausiert." : "Yami wird mit deinem Chat verbunden. Das kann etwa eine Minute dauern.")}>{channel.enabled ? "Bot pausieren / entfernen" : "Bot zu meinem Channel hinzufügen"}</button>
                  <div className="mt-6 grid gap-4 sm:grid-cols-2">
                    <Field label="Command-Präfix" htmlFor="twitch-prefix" hint="1–3 Zeichen aus ! ? . $"><input id="twitch-prefix" className="field" required pattern="[!?.$]{1,3}" maxLength={3} value={settings.prefix} onChange={e => update("prefix", e.target.value)} /></Field>
                    <Field label="Command-Cooldown (Sekunden)" htmlFor="twitch-cooldown" hint="Pro Person; Blackjack-Aktionen: 1 Sekunde."><input id="twitch-cooldown" className="field" type="number" required min={2} max={120} value={settings.command_cooldown} onChange={e => update("command_cooldown", Number(e.target.value))} /></Field>
                  </div>
                </Section>
                <Section title="Community & Spiele">
                  <div className="space-y-3"><Toggle title="Social-Commands" hint="Hugs, Freundschaften, Heiratsanträge und mehr." value={settings.social_enabled} onChange={v => update("social_enabled", v)} /><Toggle title="Gambling" hint="Coinflip, Slots, Roulette, Blackjack und Duelle." value={settings.gambling_enabled} onChange={v => update("gambling_enabled", v)} /></div>
                  <div className="mt-5 grid gap-4 sm:grid-cols-2">
                    <Field label="Maximaler Einsatz" htmlFor="twitch-bet" hint="1–100.000 virtuelle Coins pro Einsatz."><input id="twitch-bet" className="field" type="number" required min={1} max={100000} value={settings.max_bet} onChange={e => update("max_bet", Number(e.target.value))} /></Field>
                    <Field label="Tägliche Channel-Coins" htmlFor="twitch-daily" hint="Bei Discord-Verknüpfung gilt das gemeinsame Discord-Daily."><input id="twitch-daily" className="field" type="number" required min={1} max={10000} value={settings.daily_coins} onChange={e => update("daily_coins", Number(e.target.value))} /></Field>
                  </div>
                  <p className="mt-4 text-sm text-muted">Nur virtuelle Coins, keine Käufe oder Auszahlungen. Discord-Shop-Effekte gelten nicht in Twitch-Spielen.</p>
                </Section>
                <Section title="Automatische Nachrichten">
                  <TwitchAutoMessages messages={settings.auto_messages ?? []} botName={data?.bot_login ?? "Yami"} onChange={messages => update("auto_messages", messages)} />
                </Section>
                <Section title="AutoMod">
                  <Toggle title="AutoMod aktivieren" hint="Eigene Chat-Filter zusätzlich zu Twitchs integriertem AutoMod. Broadcaster und Moderatoren sind ausgenommen." value={settings.automod_enabled} onChange={v => update("automod_enabled", v)} />
                  <div className="mt-4 space-y-3"><Toggle title="Links filtern" hint="Webadressen aus Zuschauernachrichten entfernen." value={settings.block_links} onChange={v => update("block_links", v)} /><Toggle title="Spam filtern" hint="6 Nachrichten oder 3 gleiche Nachrichten in 8 Sekunden." value={settings.block_spam} onChange={v => update("block_spam", v)} /><Toggle title="Großbuchstaben filtern" hint="Ab 12 Buchstaben und mindestens 80 % Großbuchstaben." value={settings.block_caps} onChange={v => update("block_caps", v)} /></div>
                  <div className="mt-5 space-y-4"><Field label="Gesperrte Begriffe" htmlFor="twitch-words" hint="Ein Begriff pro Zeile, maximal 100 mit je 80 Zeichen. Treffer auch innerhalb längerer Wörter."><textarea id="twitch-words" rows={4} className="field" value={words} onChange={e => { setWords(e.target.value); setDirty(true); }} /></Field><Field label="Timeout (Sekunden)" htmlFor="twitch-timeout" hint="0 = nur die Nachricht löschen. Maximal 1.209.600 Sekunden (14 Tage)."><input id="twitch-timeout" type="number" required min={0} max={1209600} className="field" value={settings.timeout_seconds} onChange={e => update("timeout_seconds", Number(e.target.value))} /></Field></div>
                </Section>
                <div className="flex flex-wrap items-center gap-4"><button type="submit" className="btn-primary">{busy ? "Wird gespeichert…" : "Einstellungen speichern"}</button><span className="text-sm text-muted" role="status">{dirty ? "Ungespeicherte Änderungen" : "Einstellungen sind gespeichert"}</span></div>
              </fieldset>
            </form>
            <aside className="min-w-0 space-y-6">
              <Section title="Deine Coins, verbunden">
                <div className="mb-4 flex items-center gap-3 text-violet"><Icon name="twitch" size={25} /><span>+</span><Icon name="discord" size={25} /></div>
                <p className="mb-4 text-sm leading-relaxed text-muted">Ohne Verknüpfung sammelst du eigene Coins pro Twitch-Channel. Mit Discord nutzt du überall dein Discord-Guthaben und ein gemeinsames Daily. Bestehende Twitch-Coins bleiben separat gespeichert.</p>
                {data?.discord_link ? <><p className="mb-4 text-sm">Verbunden mit <strong>{data.discord_link.name}</strong>.</p><button disabled={busy} className="btn btn-ghost" onClick={() => void action("discord-link", { linked: false }, "Discord-Verknüpfung getrennt. Deine Guthaben bleiben erhalten.")}>Verknüpfung trennen</button></>
                  : data?.discord_session ? <><p className="mb-3 text-sm">Discord: <strong>{data.discord_session.name}</strong></p><button disabled={busy} className="btn btn-ghost" onClick={() => void action("discord-link", { linked: true }, "Discord-Guthaben wird jetzt auch auf Twitch verwendet.")}>Dieses Discord-Konto verbinden</button></>
                    : <a href="/login?return_to=%2Ftwitch" className="btn btn-ghost"><Icon name="discord" size={18} />Mit Discord anmelden</a>}
              </Section>
              <Section title="Coin-Rangliste">
                {data?.leaderboard?.length ? <ol className="space-y-4">{data.leaderboard.map((row, i) => <li key={`${row.login}-${i}`} className="flex items-center gap-3 text-sm"><span className="w-5 text-muted">{i + 1}.</span><span className="min-w-0 flex-1 truncate">{row.login}</span><strong className="font-mono">{row.coins.toLocaleString("de-DE")}</strong></li>)}</ol> : <p className="text-sm text-muted">Hier erscheinen deine Zuschauer, sobald sie im Chat schreiben. Mit {prefix}daily geht’s los.</p>}
              </Section>
              <Section title="Letzte AutoMod-Aktionen">
                {data?.moderation_log?.length ? <ul className="space-y-4">{data.moderation_log.map((row, i) => <li key={`${row.created}-${i}`} className="border-b border-line pb-3 text-sm last:border-0 last:pb-0"><strong>{row.login}</strong><p className="mt-1 text-muted">{row.reason} · {row.action === "timeout" ? "Timeout" : "Nachricht gelöscht"}</p><p className="mt-1 text-xs text-muted">{new Date(row.created * 1000).toLocaleString("de-DE")} · {row.outcome === "ok" ? "Ausgeführt" : row.outcome === "failed" ? "Fehlgeschlagen" : "Ausstehend"}</p></li>)}</ul> : <p className="text-sm text-muted">Noch keine Aktionen. Wenn ein Filter greift, siehst du das Ergebnis hier.</p>}
              </Section>
            </aside>
          </div>
        </>}

        <section id="commands" className="scroll-mt-8 border-t border-line pt-10 mt-12">
          <div className="mb-7 flex flex-wrap items-end justify-between gap-4"><div><p className="mb-2 text-sm font-semibold text-violet">DIREKT IM CHAT</p><h2 className="font-display text-3xl font-bold">Ein Command reicht.</h2></div><p className="max-w-md text-sm text-muted">{auth ? `Dein Präfix: ${prefix}. ` : "Standard-Präfix: !. "}Namen mit @ angeben. Für Anfragen muss die andere Person schon einmal im Channel geschrieben haben.</p></div>
          <div className="grid gap-x-10 md:grid-cols-2">{data?.commands.map(command => <div key={command.usage} className="border-b border-line py-4"><code className="break-words text-sm font-semibold text-violet">{prefix}{command.usage}</code><p className="mt-1 text-sm text-muted">{command.description}</p></div>)}</div>
          <p className="mt-5 text-sm text-muted">Blackjack pausiert maximal 120 Sekunden, danach wird automatisch abgerechnet. Unbeantwortete Duellanfragen erstatten den Einsatz. Alle Spiele und Social-Verbindungen laufen im jeweiligen Channel.</p>
        </section>
      </main>
      <footer className="flex flex-wrap justify-between gap-4 border-t border-line py-6 text-sm text-muted"><span>Yamikun für deine Community.</span><Link to="/">Zum Discord-Dashboard</Link></footer>
    </div>
  </div>;
}
