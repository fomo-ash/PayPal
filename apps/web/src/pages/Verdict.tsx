import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CodeView, ErrorNote, HoldBar, Spinner, StatePill } from "../components";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { MOVING, pct, SETTLED, usd } from "../lib/format";
import type { Finding, Receipt, SubmissionView } from "../lib/types";

const RAIL = [
  { key: "SUBMITTED", label: "Submitted" },
  { key: "GRADING", label: "Sandbox tests" },
  { key: "JUDGING", label: "AI review" },
  { key: "SETTLE", label: "PayPal settles" },
  { key: "DONE", label: "Done" },
];

function railIndex(state: string): number {
  if (state === "SUBMITTED") return 0;
  if (state === "GRADING") return 1;
  if (state === "JUDGING" || state === "HUMAN_REVIEW") return 2;
  if (["CAPTURING", "PAYING_OUT", "VOIDING"].includes(state)) return 3;
  return 4;
}

export default function Verdict() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const [view, setView] = useState<SubmissionView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [buyer, setBuyer] = useState(false);

  const load = useCallback(() => api<SubmissionView>(`/submissions/${id}`).then((v) => { setView(v); return v; }), [id]);

  useEffect(() => {
    if (!user) return;
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const v = await load();
        if (!stop && (MOVING.has(v.job_state) || v.job_state === "CLAIMED")) timer = window.setTimeout(tick, 3000);
        else if (!stop && v.job_state === "HUMAN_REVIEW") timer = window.setTimeout(tick, 8000);
      } catch (e) {
        setError((e as Error).message);
      }
    };
    tick();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [user, load]);

  useEffect(() => {
    if (view) api(`/jobs/${view.job_id}`).then((j) => setBuyer("validated" in j)).catch(() => {});
  }, [view?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!user) return <div className="empty"><h2>Log in to see this verdict</h2><Link className="btn" to={`/login?next=/submissions/${id}`}>Log in</Link></div>;
  if (error) return <ErrorNote error={error} />;
  if (!view) return <Spinner label="Loading the verdict" />;

  const v = view.verdict;
  const settled = SETTLED.has(view.job_state);
  const at = railIndex(view.job_state);
  const findings: Finding[] = [
    ...(view.ai_review?.findings ?? []),
    ...view.scan_findings.map((f) => ({ file: f.file, line: f.line, category: f.rule, evidence: f.message })),
  ];
  const groups = Array.from(new Set(view.runs.map((r) => r.group))).sort();

  return (
    <article className="verdict">
      <header className="job__head">
        <div>
          <p className="eyebrow">Verdict · <Link to={`/jobs/${view.job_id}`}>job {view.job_id.slice(0, 8)}</Link></p>
          <h1>{headline(view)}</h1>
        </div>
        <StatePill state={view.job_state} />
      </header>

      <ol className="rail" aria-label="Progress">
        {RAIL.map((s, i) => (
          <li key={s.key} className={i < at ? "done" : i === at ? (MOVING.has(view.job_state) ? "now is-moving" : "now") : ""}>{s.label}</li>
        ))}
      </ol>

      {v ? (
        <section className="panel">
          <div className="score">
            <div>
              <span className="score__big num">{pct(v.score)}</span>
              <span className="muted">score · {v.settlement === "VOID" ? "voided" : v.settlement === "HUMAN_REVIEW" ? "sent to a reviewer" : "captured"}</span>
            </div>
            <p className="score__why">{reasonText(v.reason)}{v.decided_by && v.decided_by !== "policy" ? ` · decided by ${v.decided_by}` : ""}</p>
          </div>
          <HoldBar amount={String(Number(v.capture) + Number(v.released))} worker={v.worker_amount} fee={v.fee} released={v.released} settled={settled} />
        </section>
      ) : (
        <Spinner label={view.job_state === "SUBMITTED" ? "Queued for the sandbox" : "Running hidden tests and 200 fresh inputs in the sandbox"} />
      )}

      {view.runs.length > 0 && (
        <section className="block">
          <h2>Tests</h2>
          <table className="tbl">
            <thead><tr><th>Group</th><th>Hidden tests</th><th>Fresh inputs</th></tr></thead>
            <tbody>
              {groups.map((g) => {
                const h = view.runs.find((r) => r.group === g && r.kind === "hidden");
                const f = view.runs.find((r) => r.group === g && r.kind === "fresh");
                return (
                  <tr key={g}>
                    <td>{g}</td>
                    <td className="num"><Ratio r={h} /></td>
                    <td className="num"><Ratio r={f} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted small">A group pays the lower of its two rates. Expected answers never enter the sandbox.</p>
        </section>
      )}

      {(view.ai_review || view.scan_findings.length > 0) && (
        <section className="block">
          <h2>Checks</h2>
          {view.scan_findings.length > 0 && (
            <ul className="findings">
              {view.scan_findings.map((f, i) => (
                <li key={i} className={f.hard_signal ? "bad" : ""}>
                  <span className="tag">{f.hard_signal ? "hard signal" : "scanner"}</span>
                  <span className="mono">{f.file}:{f.line}</span> {f.message}
                </li>
              ))}
            </ul>
          )}
          {view.ai_review && (
            <div className={`ai ai--${view.ai_review.decision === "CLEAR" ? "ok" : "flag"}`}>
              <p><span className="tag">AI review</span> <b>{view.ai_review.decision.replaceAll("_", " ").toLowerCase()}</b> <span className="muted small mono">{view.ai_review.model}</span></p>
              <p>{view.ai_review.explanation}</p>
              {view.ai_review.findings.length > 0 && (
                <ul className="findings">
                  {view.ai_review.findings.map((f, i) => (
                    <li key={i}><span className="mono">{f.file}:{f.line}</span> <b>{f.category?.replaceAll("_", " ")}</b> {f.evidence}</li>
                  ))}
                </ul>
              )}
              <p className="muted small">The AI cannot raise a payment, and cannot block one alone: a flag only sends the case to a person.</p>
            </div>
          )}
        </section>
      )}

      {buyer && <BuyerCode subId={view.id} state={view.job_state} findings={findings} onReleased={load} />}
      {settled && view.job_state !== "PAYOUT_FAILED" && <ReceiptCard jobId={view.job_id} />}
    </article>
  );
}

function Ratio({ r }: { r?: { passed: number; total: number } }) {
  if (!r) return <>—</>;
  const ok = r.passed === r.total;
  return <span className={ok ? "ok-ink" : r.passed / r.total < 0.5 ? "bad-ink" : ""}>{r.passed}/{r.total}</span>;
}

function headline(v: SubmissionView): string {
  const d = v.verdict;
  if (!d) return "Grading the submission";
  if (v.job_state === "HUMAN_REVIEW") return "Flagged: a person decides";
  if (d.settlement === "VOID") return `Voided. The buyer keeps all ${usd(Number(d.capture) + Number(d.released))}.`;
  return `${usd(d.capture)} captured, ${usd(d.released)} back to the buyer`;
}

function reasonText(r: string): string {
  if (r === "clear") return "All checks clear.";
  if (r.startsWith("score below")) return "Below the buyer's minimum score.";
  return r;
}

function BuyerCode({ subId, state, findings, onReleased }: { subId: string; state: string; findings: Finding[]; onReleased: () => void }) {
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const can = state === "PAID" || state === "CODE_RELEASED";

  async function get() {
    try {
      const r = await api<{ files: Record<string, string> }>(`/submissions/${subId}/code`);
      setFiles(r.files);
      onReleased();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="block">
      <h2>The code</h2>
      {!can && <p className="muted">{state === "VOIDED" ? "Nothing was paid, so the code is not released to you." : "Released to you once the worker is paid."}</p>}
      {can && !files && <button className="btn" onClick={get}>Get the code</button>}
      <ErrorNote error={error} />
      {files && <CodeView files={files} findings={findings} />}
    </section>
  );
}

function ReceiptCard({ jobId }: { jobId: string }) {
  const [doc, setDoc] = useState<Receipt | null>(null);
  const [valid, setValid] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Receipt>(`/receipts/${jobId}`).then(setDoc).catch((e) => setError(e.message));
  }, [jobId]);

  async function verify() {
    if (!doc) return;
    try {
      const r = await api<{ valid: boolean }>("/receipts/verify", { body: doc });
      setValid(r.valid);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function download() {
    if (!doc) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `verdict-receipt-${jobId.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (error) return <ErrorNote error={error} />;
  if (!doc) return null;
  const p = doc.receipt.paypal;
  return (
    <section className="block receipt">
      <h2>Signed receipt</h2>
      <dl className="facts facts--ids">
        <div><dt>PayPal order</dt><dd className="mono">{p.order_id ?? "—"}</dd></div>
        <div><dt>Authorization (hold)</dt><dd className="mono">{p.authorization_id ?? "—"}</dd></div>
        <div><dt>Capture</dt><dd className="mono">{p.capture_id ?? "none, voided"}</dd></div>
        <div><dt>Payout batch</dt><dd className="mono">{p.payout_batch_id ?? "—"}</dd></div>
        <div><dt>Audit chain head</dt><dd className="mono">{doc.receipt.audit_head_hash?.slice(0, 24)}…</dd></div>
        <div><dt>Signature (Ed25519)</dt><dd className="mono">{doc.signature.slice(0, 24)}…</dd></div>
      </dl>
      <div className="row">
        <button className="btn btn--ghost" onClick={verify}>Check the signature</button>
        <button className="btn btn--ghost" onClick={download}>Download JSON</button>
        <Link to="/verify" className="muted small">Anyone can verify a receipt →</Link>
      </div>
      {valid !== null && (
        <p className={`note ${valid ? "note--ok" : "note--err"}`}>{valid ? "Valid: signed by Verdict's key and unchanged." : "Invalid signature."}</p>
      )}
    </section>
  );
}
