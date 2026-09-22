import { useState, type FormEvent } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, errText } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Icon } from "../components/Icon";
import { PageHeader, Panel } from "../components/common";

type Kind = "bug" | "feature";

export default function Support() {
  const { gid } = useParams();
  const location = useLocation();
  const { push } = useToast();
  const [kind, setKind] = useState<Kind>("bug");
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [sentKind, setSentKind] = useState<Kind | null>(null);
  const isAdminPanel = location.pathname.startsWith("/g/");
  const backTarget = isAdminPanel ? `/g/${gid}/overview` : `/u/${gid}`;
  const backLabel = isAdminPanel ? "Zurück zum Admin-Menü" : "Zurück zum Menü";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/api/u/${gid}/feedback`, { kind, title, details });
      push("ok", kind === "bug" ? "Bugreport wurde gesendet. Danke dir!" : "Feature-Wunsch wurde gesendet. Danke dir!");
      setSentKind(kind);
      setTitle("");
      setDetails("");
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  if (sentKind) {
    return (
      <>
        <PageHeader title="Nachricht gesendet" subtitle="Danke dir — deine Meldung ist beim Yamikun-Team angekommen" />

        <Panel className="support-success-panel">
          <div className="support-success">
            <div className="support-success-orb">
              <Icon name="check" size={30} />
            </div>
            <div>
              <p className="support-success-kicker">
                {sentKind === "bug" ? "Bugreport gesendet" : "Feature-Wunsch gesendet"}
              </p>
              <h2>Vielen Dank für deine Rückmeldung</h2>
              <p>
                Deine Nachricht wurde erfolgreich an das Yamikun-Team übermittelt. Wir prüfen dein
                Anliegen und melden uns bei dir, falls noch Rückfragen offen sind.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <Link to={backTarget} className="btn-primary">
                  <Icon name="arrow" size={17} className="rotate-180" />
                  {backLabel}
                </Link>
                <button type="button" className="btn" onClick={() => setSentKind(null)}>
                  Noch eine Nachricht senden
                </button>
              </div>
            </div>
          </div>
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Support & Wünsche" subtitle="Bugs melden oder neue Ideen für Yamikun vorschlagen" />

      <Panel title="💜 Nachricht ans Yamikun-Team">
        <div className="support-intro">
          <div className="support-intro-icon">
            <Icon name="sparkle" size={22} />
          </div>
          <div>
            <h3>Direkt ans Team</h3>
            <p>
              Deine Meldung landet privat bei den WebOwnern. Schreib kurz, was passiert ist
              oder welche Idee du hast — je klarer die Nachricht, desto schneller kann sie
              geprüft werden.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-5 grid gap-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => setKind("bug")}
              className={`support-choice ${kind === "bug" ? "active" : ""}`}
            >
              <Icon name="alert" size={20} />
              <span>
                <b>Bug reporten</b>
                <small>Etwas funktioniert nicht richtig.</small>
              </span>
            </button>
            <button
              type="button"
              onClick={() => setKind("feature")}
              className={`support-choice ${kind === "feature" ? "active" : ""}`}
            >
              <Icon name="sparkle" size={20} />
              <span>
                <b>Feature anfragen</b>
                <small>Eine neue Idee fürs Webpanel oder den Bot.</small>
              </span>
            </button>
          </div>

          <label className="grid gap-2">
            <span className="text-sm font-semibold text-muted">Kurz-Titel</span>
            <input
              className="field"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={100}
              placeholder={kind === "bug" ? "z.B. Lieblingskarte wird doppelt angezeigt" : "z.B. Mehr Profil-Themes"}
              required
            />
            <span className="text-right text-xs text-faint">{title.length}/100</span>
          </label>

          <label className="grid gap-2">
            <span className="text-sm font-semibold text-muted">Beschreibung</span>
            <textarea
              className="field min-h-[170px] resize-y leading-relaxed"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              maxLength={1000}
              placeholder={
                kind === "bug"
                  ? "Was ist passiert? Was hast du davor gemacht? Was hättest du erwartet?"
                  : "Was soll die Funktion können? Wo würdest du sie im Bot oder Webpanel nutzen?"
              }
              required
            />
            <span className="text-right text-xs text-faint">{details.length}/1000</span>
          </label>

          <div className="support-hint-grid">
            <div>
              <b>{kind === "bug" ? "Für Bugs hilfreich" : "Für Wünsche hilfreich"}</b>
              <span>
                {kind === "bug"
                  ? "Schritte zum Nachmachen, betroffener Bereich und was falsch angezeigt wird."
                  : "Kurzer Zweck, gewünschtes Verhalten und warum es für den Server nützlich wäre."}
              </span>
            </div>
            <div>
              <b>Versand</b>
              <span>Die Nachricht wird als übersichtliche Discord-DM ans Team gesendet.</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button disabled={busy} className="btn-primary" type="submit">
              <Icon name={busy ? "loader" : "arrow"} size={17} className={busy ? "animate-spin" : ""} />
              {busy ? "Wird gesendet…" : kind === "bug" ? "Bugreport senden" : "Feature-Wunsch senden"}
            </button>
            <span className="text-sm text-faint">Zum Schutz vor Spam gibt es einen kurzen Cooldown.</span>
          </div>
        </form>
      </Panel>
    </>
  );
}
