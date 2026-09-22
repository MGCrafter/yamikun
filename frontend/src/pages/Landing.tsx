import { motion } from "motion/react";
import { useSearchParams, Link } from "react-router-dom";
import { Aurora } from "../components/ui/Aurora";
import { Icon } from "../components/Icon";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { useAuth } from "../lib/auth";

const ERRORS: Record<string, string> = {
  no_access:
    "Du hast auf keinem Server, auf dem dieser Bot ist, die Berechtigung „Server verwalten“.",
  state: "Login abgebrochen oder abgelaufen — bitte erneut versuchen.",
  token: "Token-Tausch mit Discord fehlgeschlagen.",
  profile: "Discord-Profil konnte nicht geladen werden.",
};

const FEATURES = [
  { icon: "layers", title: "Sammelkarten", text: "Karten hochladen, benennen, nach Spiel & Seltenheit verwalten." },
  { icon: "coins", title: "Economy", text: "Coins, XP und Level deiner Mitglieder im Blick — und anpassbar." },
  { icon: "box", title: "Inventare", text: "Wer besitzt was? Sammlungen einsehen und aufräumen." },
  { icon: "gamepad", title: "Drops & Spiele", text: "Booster-Belohnungen pro Spiel und Drop-Channel einstellen." },
];

export default function Landing() {
  const [params] = useSearchParams();
  const err = params.get("error");
  const { me } = useAuth();

  return (
    <Aurora className="min-h-screen">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-6">
        {/* Topbar */}
        <header className="flex items-center justify-between py-6">
          <div className="flex items-center gap-2.5 font-display text-lg font-bold">
            <img src="/assets/YamiKun.webp" alt="" className="h-9 w-9 rounded-lg object-cover" />
            Yamikun
          </div>
          <div className="flex items-center gap-2.5">
            <Link to="/twitch" className="btn btn-ghost">Twitch</Link>
            {me?.authenticated ? (
              <Link to="/app" className="btn btn-ghost">
                Zum Dashboard <Icon name="arrow" size={16} />
              </Link>
            ) : (
              <a href="/login" className="btn btn-ghost">
                Anmelden
              </a>
            )}
            <ThemeToggle />
          </div>
        </header>

        {/* Hero */}
        <main className="flex flex-1 flex-col items-center justify-center pb-24 pt-10 text-center">
          {err && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-7 flex items-center gap-2.5 rounded-xl border border-danger/40 bg-danger/[0.12] px-4 py-3 text-sm text-[#ffb4b4]"
            >
              <Icon name="alert" size={17} />
              {ERRORS[err] ?? "Es ist ein Fehler aufgetreten."}
            </motion.div>
          )}

          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="mb-5 inline-flex items-center gap-2 rounded-full border border-line2 bg-panel/60 px-4 py-1.5 text-[0.8rem] text-muted backdrop-blur"
          >
            <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_10px] shadow-accent" />
            Yamikuns Kommandozentrale
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.05 }}
            className="font-display text-5xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl"
          >
            Dein Turm. Deine Regeln.
            <br />
            <span className="bg-gradient-to-r from-accent via-accent to-[#7aa0ff] bg-clip-text text-transparent">
              Yami hält die Wache.
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.12 }}
            className="mt-6 max-w-xl text-balance text-[1.05rem] leading-relaxed text-muted"
          >
            Forme Yamikuns Welt nach deinen Vorstellungen: von Sammelkarten und Economy bis zu Drops,
            Rollen und Server-Momenten. Direkt, lebendig und ohne Umwege.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="mt-9"
          >
            {me?.authenticated ? (
              <Link to="/app" className="btn-primary px-7 py-3 text-base">
                Zum Dashboard <Icon name="arrow" size={18} />
              </Link>
            ) : (
              <motion.a
                href="/login"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.98 }}
                className="btn-primary px-7 py-3 text-base"
              >
                <Icon name="discord" size={20} /> Mit Discord anmelden
              </motion.a>
            )}
          </motion.div>

          {/* Feature-Karten */}
          <div className="mt-20 grid w-full grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.3 + i * 0.08 }}
                whileHover={{ y: -4 }}
                className="rounded-xl border border-line bg-panel/70 p-5 text-left backdrop-blur"
              >
                <div className="mb-3 grid h-10 w-10 place-items-center rounded-lg bg-panel2 text-accent">
                  <Icon name={f.icon} size={20} />
                </div>
                <div className="font-display font-semibold">{f.title}</div>
                <p className="mt-1.5 text-[0.85rem] leading-relaxed text-muted">{f.text}</p>
              </motion.div>
            ))}
          </div>
        </main>
      </div>
    </Aurora>
  );
}
