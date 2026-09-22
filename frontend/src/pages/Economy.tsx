import { useAuth } from "../lib/auth";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useApiData } from "../lib/useApiData";
import { api, errText, type EconomyData } from "../lib/api";
import { useToast } from "../components/ui/Toast";
import { Avatar } from "../components/ui/Avatar";
import { fmtNum } from "../lib/utils";
import { PageHeader, Panel, InfoBanner, Spinner } from "../components/common";
import { Field } from "../components/ui/Field";
import { useValidation } from "../lib/useValidation";
import { required, intRange } from "../lib/validators";

const COIN_MAX = 1_000_000_000;

export default function Economy() {
  const { gid } = useParams();
  const { me } = useAuth();
  const { push } = useToast();
  const [scope, setScope] = useState<"guild" | "all">("guild");
  const { data, loading, reload } = useApiData<EconomyData>(`/api/g/${gid}/economy?scope=${scope}`);
  const [userId, setUserId] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const v = useValidation(
    { user_id: userId, amount },
    {
      user_id: [required("Bitte einen Nutzer wählen.")],
      amount: [
        required("Bitte einen Betrag angeben."),
        intRange(-COIN_MAX, COIN_MAX, "Bitte eine ganze Zahl im erlaubten Bereich."),
      ],
    },
  );

  if (loading || !data) return <Spinner />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!v.validateAll()) return;
    setBusy(true);
    try {
      await api.post(`/api/g/${gid}/economy/coins`, { user_id: userId, amount });
      push("ok", "Coins angepasst.");
      setAmount("");
      reload();
    } catch (err) {
      push("err", errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Economy" subtitle={`${data.leaderboard.length} Nutzer`} />
      <InfoBanner>Coins, XP und Level sind global — serverübergreifend pro Nutzer.</InfoBanner>

      <div className="mb-4 mt-1 flex items-center gap-3">
        <span className="eyebrow">Anzeige</span>
        <div className="seg">
          {(["guild", "all"] as const).map((k) => (
            <button key={k} data-on={scope === k} onClick={() => setScope(k)}>
              {k === "guild" ? "Nur dieser Server" : "Alle Server"}
            </button>
          ))}
        </div>
      </div>

      {me?.can_manage_global_assets && <Panel title="Coins anpassen">
        <p className="mb-4 text-sm text-muted">Positiver Wert gutschreiben, negativer abziehen.</p>
        <form onSubmit={submit} className="coin-form">
          <Field label="Nutzer" required error={v.showError("user_id")}>
            <select
              className="field"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              onBlur={v.blur("user_id")}
            >
              <option value="">— Nutzer wählen —</option>
              {data.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Betrag" required error={v.showError("amount")}>
            <input
              className="field"
              type="number"
              step="1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onBlur={v.blur("amount")}
              placeholder="z. B. 1000 oder -500"
            />
          </Field>
          <button className="btn-primary" disabled={busy || !v.isValid}>
            Übernehmen
          </button>
        </form>
      </Panel>}

      <Panel title="Leaderboard">
        <div className="overflow-x-auto">
          <table className="lb">
            <thead>
              <tr>
                <th>#</th>
                <th>Nutzer</th>
                <th>Level</th>
                <th>XP</th>
                <th>Coins</th>
              </tr>
            </thead>
            <tbody>
              {data.leaderboard.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-7 text-center text-faint">
                    Noch keine Nutzer.
                  </td>
                </tr>
              )}
              {data.leaderboard.map((r) => {
                const medal = r.rank === 1 ? "🥇" : r.rank === 2 ? "🥈" : r.rank === 3 ? "🥉" : null;
                return (
                  <tr key={r.user_id}>
                    <td>{medal ? <span className="text-[17px]">{medal}</span> : r.rank}</td>
                    <td>
                      <span className="lb-user">
                        <Avatar src={r.avatar} name={r.name} size={30} />
                        <span className="nm">{r.name}</span>
                      </span>
                    </td>
                    <td className="num">{r.level}</td>
                    <td className="num">{fmtNum(r.xp)}</td>
                    <td className="coins">{fmtNum(r.coins)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
