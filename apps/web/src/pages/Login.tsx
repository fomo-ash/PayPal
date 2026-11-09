import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNote } from "../components";
import { useAuth } from "../lib/auth";
import type { Role } from "../lib/types";

const ROLES: { role: Role; title: string; body: string; next: string }[] = [
  { role: "buyer", title: "Buyer", body: "Post a job with hidden tests, then put a PayPal hold on the budget.", next: "/jobs/new" },
  { role: "worker", title: "Worker", body: "Take an open job, try the public examples, submit once, get paid for what passes.", next: "/" },
  { role: "admin", title: "Reviewer", body: "Decide cases the AI flagged. You can lower a payment or void it, never raise it.", next: "/review" },
];

export default function Login() {
  const { demoLogin, paypalLogin, config } = useAuth();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const want = params.get("as");
  const back = params.get("next");

  async function demo(role: Role, next: string) {
    setBusy(role);
    setError(null);
    try {
      await demoLogin(role);
      nav(back || next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="narrow">
      <h1>Choose who you are</h1>
      <p className="lede">
        Each try gives you a fresh account in the PayPal sandbox. No real money moves. To fund a job you approve
        the hold with a PayPal sandbox buyer account (credentials are in the project's Devpost page).
      </p>
      <ErrorNote error={error} />
      <div className="roles">
        {ROLES.map((r) => (
          <article key={r.role} className={`role-card ${want === r.role ? "is-wanted" : ""}`}>
            <h2>{r.title}</h2>
            <p>{r.body}</p>
            {config?.demo_login !== false && (
              <button className="btn" disabled={!!busy} onClick={() => demo(r.role, r.next)}>
                {busy === r.role ? "Signing in…" : `Try as ${r.title.toLowerCase()}`}
              </button>
            )}
            {config?.paypal_login && r.role !== "admin" && (
              <button className="btn btn--paypal" disabled={!!busy}
                onClick={() => paypalLogin(r.role as "buyer" | "worker").catch((e) => setError(e.message))}>
                Log in with PayPal
              </button>
            )}
          </article>
        ))}
      </div>
      {config && !config.demo_login && !config.paypal_login && (
        <p className="note">Logins are switched off on this server.</p>
      )}
    </section>
  );
}
