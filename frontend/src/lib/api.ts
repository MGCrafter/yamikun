// Schmaler Fetch-Client gegen die Bot-API. Alle Discord-IDs sind Strings.

export type Rarity = { key: string; label: string; color: string };
export type Guild = { id: string; name: string };

export type Me = {
  authenticated: boolean;
  username?: string;
  avatar?: string | null;
  can_edit_cards?: boolean;
  can_manage_global_assets?: boolean;
  csrf?: string;
  guilds?: Guild[];
  member_guilds?: Guild[];
  rarities: Rarity[];
};

export type Card = {
  id: string;
  name: string;
  rarity: string;
  rarity_label: string;
  color: string;
  url: string | null;
  game?: string;
  count?: number;
};

export type Overview = {
  guild: Guild;
  stats: {
    card_types: number;
    games: number;
    collectors: number;
    total_owned: number;
    channel_label: string;
  };
  rarity_distribution: { key: string; label: string; color: string; count: number }[];
};

export type GameCfg = {
  name: string;
  interval: number;
  cap: number;
  emoji: string;
  emoji_display: string;
  aliases: string[];
};
export type GamesData = {
  guild: Guild;
  games: GameCfg[];
  channels: { id: string; name: string }[];
  channel_id: string | null;
};

export type EconomyRow = {
  rank: number;
  user_id: string;
  name: string;
  avatar?: string | null;
  level: number;
  xp: number;
  coins: number;
};
export type EconomyData = {
  users: { id: string; name: string }[];
  leaderboard: EconomyRow[];
};

export type Collector = {
  user_id: string;
  name: string;
  avatar?: string | null;
  game_count: number;
  yami_count: number;
};
export type InventoryUser = {
  user_id: string;
  name: string;
  avatar?: string | null;
  game_cards: Card[];
  yami_cards: Card[];
};

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

let csrfToken = "";
export function setCsrf(token: string) {
  csrfToken = token;
}

async function handle(res: Response) {
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const j = await res.json();
      if (j?.error) code = j.error;
    } catch {
      /* kein JSON-Body */
    }
    throw new ApiError(res.status, code);
  }
  return res.json();
}

export const api = {
  async get(path: string) {
    const res = await fetch(path, { credentials: "include" });
    return handle(res);
  },
  async post(path: string, body?: unknown) {
    const res = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify(body ?? {}),
    });
    return handle(res);
  },
  // Multipart-Upload (Datei). CSRF geht als Header mit.
  async upload(path: string, form: FormData) {
    const res = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
      body: form,
    });
    return handle(res);
  },
};

export const UPLOAD_ERRORS: Record<string, string> = {
  size: "Datei zu groß — maximal 70 MB erlaubt.",
  type: "Dateityp nicht unterstützt — erlaubt sind PNG, JPG, GIF und WebP.",
  fields: "Bitte alle Felder ausfüllen.",
  noimg: "Bitte ein Bild auswählen.",
  name: "Ungültiger Name — mindestens ein Buchstabe oder eine Ziffer nötig.",
  bad_csrf: "Sitzung abgelaufen — bitte Seite neu laden.",
  card_editor_only: "Das Verwalten von Karten ist auf bestimmte Personen beschränkt.",
  not_enough: "Du brauchst 5 Karten dieser Seltenheit.",
  no_target: "Es gibt keine Karte der nächsthöheren Seltenheit in diesem Pool.",
  no_next: "Diese Seltenheit lässt sich nicht fusionieren (Legendary ist das Maximum).",
  no_cards: "Hier gibt es keine Karten.",
  no_duplicate: "Nur Duplikate können zerlegt werden — ein Exemplar bleibt immer im Album.",
  card_not_found: "Diese Spielkarte existiert nicht mehr.",
  game_not_found: "Dieses Spiel hat keinen Kartenpool.",
  not_enough_shards: "Du hast nicht genügend Arkansplitter für diesen Booster.",
  global_owner_only: "Nur globale Owner dürfen Guthaben und Inventare ändern.",
  forbidden: "Kein Zugriff.",
  cooldown: "Bitte warte ein paar Minuten, bevor du das nächste Spiel anfragst.",
  no_owners: "Für diesen Server sind keine WebOwner hinterlegt.",
  no_delivery: "Kein WebOwner konnte erreicht werden (DMs evtl. gesperrt).",
  already_editor: "Du kannst Spiele direkt anlegen — eine Anfrage ist nicht nötig.",
  bad_channel: "Bitte einen gültigen Text-Channel wählen.",
  forbidden_channel: "Ich darf in diesem Channel nicht schreiben.",
  too_many: "Maximal 25 Themen möglich.",
  no_guild: "Server nicht erreichbar — läuft der Bot?",
  forbidden_nick: "Dem Bot fehlt die Berechtigung zum Ändern des Nicknames.",
  nick_failed: "Nickname konnte nicht gesetzt werden.",
  avatar_unsupported: "Server-Avatar wird von Discord für Bots hier nicht unterstützt.",
  send_failed: "Nachricht konnte nicht gesendet werden.",
  empty: "Bitte gib einen Text (oder Titel) ein.",
  not_found: "Diese Nachricht wurde nicht gefunden.",
  msg_gone: "Die Nachricht gibt es auf Discord nicht mehr.",
  // Validierung / Härtung
  too_long: "Text ist zu lang — bitte kürzen (Discord-Limit überschritten).",
  bad_url: "Bitte eine gültige http(s)-Bild-URL angeben.",
  welcome_channel: "Bitte einen Willkommens-Channel wählen, wenn das System aktiviert ist.",
  boost_channel: "Bitte einen Channel wählen, wenn die Boost-Nachricht aktiviert ist.",
  twitch_config: "Für Twitch Live bitte einen gültigen Twitch-Kanal und Discord-Channel wählen.",
  amount_range: "Betrag außerhalb des erlaubten Bereichs.",
  bad_category: "Ungültige Kategorie.",
  bad_kind: "Ungültige Auswahl.",
  bad_user: "Ungültige Nutzer-Auswahl.",
  bad_guild: "Server nicht gefunden.",
  cog_missing: "Modul ist nicht geladen.",
  message_not_found: "Die angegebene Nachricht wurde nicht gefunden.",
  forbidden_reaction: "Dem Bot fehlt die Berechtigung, Reaktionen hinzuzufügen.",
  invalid_emoji: "Das ist kein gültiges Emoji (oder das Server-Emoji ist nicht nutzbar).",
  role_unassignable: "Diese Rolle steht über der Bot-Rolle — der Bot kann sie nicht vergeben.",
  required_role_unknown: "Die gewählte Voraussetzungs-Rolle existiert nicht (mehr).",
  unauthorized: "Nicht angemeldet — bitte neu einloggen.",
};

export function errText(e: unknown): string {
  if (e instanceof ApiError) return UPLOAD_ERRORS[e.code] ?? `Fehler (${e.code}).`;
  return "Unerwarteter Fehler.";
}
