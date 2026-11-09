import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ErrorNote, Spinner, StatePill } from "../components";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { pct, usd } from "../lib/format";
import { SAMPLE_SUBMISSIONS } from "../lib/sample";
import type { Job, SubmissionView, ValidateResult } from "../lib/types";

interface Work { job_id: string; claim_status: string; submission_id: string | null; deadline_at: string }

export default function JobPage() {
  const { id = "" } = useParams();
  const { user, ready } = useAuth();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Job>(`/jobs/${id}`).then(setJob).catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (ready && user) load();
  }, [ready, user, load]);

  if (!ready) return <Spinner label="Loading" />;
  if (!user) {
    return (
      <div className="empty">
        <h2>Log in to see this job</h2>
        <Link className="btn" to={`/login?next=/jobs/${id}`}>Log in</Link>
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;
  if (!job) return <Spinner label="Loading the job" />;

  const owner = "validated" in job;
  return (
    <article className="job">
      <header className="job__head">
        <div>
          <p className="eyebrow">{owner ? "Your job" : "Job"} · <span className="mono">{id.slice(0, 8)}</span></p>
          <h1>{job.title}</h1>
        </div>
        <StatePill state={job.state} />
      </header>

      <dl className="facts">
        <div><dt>Hold</dt><dd className="num">{usd(job.amount)}</dd></div>
        <div><dt>Minimum score</dt><dd className="num">{pct(job.min_score, 0)}</dd></div>
        <div><dt>Platform fee</dt><dd className="num">{(job.fee_bps / 100).toFixed(1)}%</dd></div>
        <div><dt>Time</dt><dd className="num">{job.deadline_hours}h</dd></div>
        <div><dt>Suite</dt><dd className="mono">{job.suite_sha256 ? `${job.suite_sha256.slice(0, 16)}… sealed` : "not sealed yet"}</dd></div>
      </dl>

      {owner ? <BuyerPanel job={job} reload={load} /> : <WorkerPanel job={job} reload={load} />}

      <section className="block">
        <h2>Scoring</h2>
        <p className="muted">Each group's rate is the lower of its hidden-test rate and its fresh-input rate, so memorizing tests does not pay.</p>
        <table className="tbl">
          <thead><tr><th>Group</th><th>Weight</th><th>Hidden tests</th><th>Fresh inputs</th></tr></thead>
          <tbody>
            {job.groups.map((g) => (
              <tr key={g.name}><td>{g.name}</td><td className="num">{pct(g.weight, 0)}</td><td className="num">{g.tests}</td><td className="num">{g.fresh_inputs || "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="block">
        <h2>Description</h2>
        <pre className="spec">{job.spec_md}</pre>
        {job.examples.length > 0 && (
          <>
            <h3>Public examples</h3>
            {job.examples.slice(0, 3).map((e, i) => (
              <div key={i} className="example">
                <pre className="mono"><b>input</b>{"\n"}{e.input}</pre>
                <pre className="mono"><b>expected</b>{"\n"}{e.expected}</pre>
              </div>
            ))}
          </>
        )}
      </section>
    </article>
  );
}

// ── buyer ────────────────────────────────────────────────────────────────────
function BuyerPanel({ job, reload }: { job: Job; reload: () => void }) {
  const [params, setParams] = useSearchParams();
  const [result, setResult] = useState<ValidateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const validate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<ValidateResult>(`/jobs/${job.id}/validate`, { method: "POST" });
      setResult(r);
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [job.id, reload]);

  useEffect(() => {
    if (params.get("validate") && job.state === "DRAFT" && !started.current) {
      started.current = true;
      setParams({}, { replace: true });
      validate();
    }
  }, [params, job.state, validate, setParams]);

  async function backToDraft() {
    try {
      await api(`/jobs/${job.id}/edit`, { method: "POST" });
      setResult(null);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="panel">
      <ErrorNote error={error} />
      {busy && <Spinner label="Running your reference on every hidden test in the sandbox, then the AI checks each test against your description. About 40 seconds." />}
      {result && <ValidationReport r={result} />}

      {job.state === "DRAFT" && !busy && (
        <div className="row">
          <button className="btn" onClick={validate}>Check the tests</button>
          <span className="muted">Nothing is held until this passes.</span>
        </div>
      )}
      {job.state === "INVALID" && (
        <div className="row">
          <button className="btn" onClick={backToDraft}>Back to draft</button>
          <span className="muted">Fix the description or the tests, then check again.</span>
        </div>
      )}
      {job.state === "AWAITING_FUNDS" && <Fund job={job} reload={reload} />}
      {job.state === "OPEN" && (
        <p className="note note--ok">
          PayPal is holding <b className="num">{usd(job.amount)}</b>. The tests are sealed. Waiting for a worker or an agent to take the job.
        </p>
      )}
      {["CLAIMED", "SUBMITTED", "GRADING", "JUDGING", "HUMAN_REVIEW", "CAPTURING", "PAYING_OUT", "PAID", "CODE_RELEASED", "VOIDING", "VOIDED", "PAYOUT_FAILED"].includes(job.state) && (
        <SubmissionLink jobId={job.id} state={job.state} />
      )}
    </section>
  );
}

function ValidationReport({ r }: { r: ValidateResult }) {
  const fair = r.spec_check.filter((x) => x.implied).length;
  const unfair = r.spec_check.filter((x) => !x.implied);
  return (
    <div className={`report ${r.state === "INVALID" ? "report--bad" : "report--ok"}`}>
      <h3>{r.state === "INVALID" ? "The tests need fixing" : "Tests checked"}</h3>
      <ul className="checks">
        <li className={r.problems.some((p) => p.includes("reference")) ? "bad" : "ok"}>Reference solution passes every hidden test and example</li>
        {r.spec_check.length > 0 && (
          <li className={unfair.length ? "bad" : "ok"}>
            AI check: {fair}/{r.spec_check.length} tests follow from your description
          </li>
        )}
      </ul>
      {r.problems.length > 0 && (
        <ul className="problems">{r.problems.map((p) => <li key={p} className="mono">{p}</li>)}</ul>
      )}
      {r.warnings.map((w) => <p key={w} className="muted">{w}</p>)}
    </div>
  );
}

function Fund({ job, reload }: { job: Job; reload: () => void }) {
  const { config } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [approveUrl, setApproveUrl] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function confirm() {
    setConfirming(true);
    setError(null);
    try {
      await api(`/jobs/${job.id}/fund/confirm`, { method: "POST" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setConfirming(false);
    }
  }

  async function openInTab() {
    try {
      const o = await api<{ approve_url: string }>(`/jobs/${job.id}/fund`, { method: "POST" });
      setApproveUrl(o.approve_url);
      window.open(o.approve_url, "_blank", "noopener");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="fund">
      <h3>Hold {usd(job.amount)} with PayPal</h3>
      <p className="muted">
        This is an <b>authorization</b>, not a payment. PayPal holds the money; Verdict later captures only the share the work earns
        and releases the rest. Use a PayPal <b>sandbox</b> buyer account.
      </p>
      {config?.paypal_client_id ? (
        <div className="fund__btns">
          <PayPalScriptProvider options={{ clientId: config.paypal_client_id, intent: "authorize", currency: "USD" }}>
            <PayPalButtons
              style={{ layout: "vertical", shape: "rect", label: "paypal", height: 44 }}
              fundingSource="paypal"
              createOrder={async () => (await api<{ order_id: string }>(`/jobs/${job.id}/fund`, { method: "POST" })).order_id}
              onApprove={async () => { await confirm(); }}
              onError={(e) => setError(String((e as { message?: string })?.message ?? e))}
            />
          </PayPalScriptProvider>
        </div>
      ) : (
        <p className="note">PayPal buttons need the client id on the server; use the link below.</p>
      )}
      <p className="muted small">
        Popup blocked? <button className="linkish" onClick={openInTab}>Open PayPal in a new tab</button>
        {approveUrl && <> then <button className="linkish" onClick={confirm} disabled={confirming}>{confirming ? "confirming…" : "I approved it"}</button></>}
      </p>
      {confirming && <Spinner label="Confirming the hold with PayPal" />}
      <ErrorNote error={error} />
    </div>
  );
}

function SubmissionLink({ jobId, state }: { jobId: string; state: string }) {
  const [sub, setSub] = useState<SubmissionView | null>(null);
  useEffect(() => {
    api<SubmissionView>(`/jobs/${jobId}/submission`).then(setSub).catch(() => setSub(null));
  }, [jobId, state]);
  if (!sub) return <p className="note">A worker has claimed the job. The verdict appears here once they submit.</p>;
  return (
    <p className="row">
      <Link className="btn" to={`/submissions/${sub.id}`}>See the verdict</Link>
      <span className="muted">Submission <span className="mono">{sub.sha256.slice(0, 12)}…</span></span>
    </p>
  );
}

// ── worker ───────────────────────────────────────────────────────────────────
function WorkerPanel({ job, reload }: { job: Job; reload: () => void }) {
  const { user } = useAuth();
  const nav = useNavigate();
  const [mine, setMine] = useState<Work | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadMine = useCallback(() => {
    api<Work[]>("/submissions/mine").then((w) => setMine(w.find((x) => x.job_id === job.id) ?? null)).catch(() => {});
  }, [job.id]);
  useEffect(loadMine, [loadMine, job.state]);

  async function claim() {
    setBusy(true);
    setError(null);
    try {
      await api(`/jobs/${job.id}/claim`, { method: "POST" });
      reload();
      loadMine();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (mine?.submission_id) {
    return (
      <section className="panel">
        <p className="row">
          <button className="btn" onClick={() => nav(`/submissions/${mine.submission_id}`)}>See your verdict</button>
        </p>
      </section>
    );
  }
  if (mine?.claim_status === "active" && job.state === "CLAIMED") {
    return <Workspace job={job} deadline={mine.deadline_at} />;
  }
  return (
    <section className="panel">
      <ErrorNote error={error} />
      {job.state === "OPEN" && user?.role === "worker" && (
        <div className="row">
          <button className="btn" onClick={claim} disabled={busy}>{busy ? "Claiming…" : "Take this job"}</button>
          <span className="muted">You get one graded submission. PayPal pays you for the share that passes.</span>
        </div>
      )}
      {job.state === "OPEN" && user?.role !== "worker" && (
        <p className="note">Log in as a worker to take this job. <Link to={`/login?as=worker&next=/jobs/${job.id}`}>Switch</Link></p>
      )}
      {job.state !== "OPEN" && <p className="note">Someone else has taken this job.</p>}
    </section>
  );
}

function Workspace({ job, deadline }: { job: Job; deadline: string }) {
  const nav = useNavigate();
  const [code, setCode] = useState("");
  const [pick, setPick] = useState("");
  const [run, setRun] = useState<{ passed: number; total: number; results: { id: string; passed: boolean; error: string | null; ms: number }[] } | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "submit">("");
  const [error, setError] = useState<string | null>(null);

  function load(key: string) {
    setPick(key);
    const s = SAMPLE_SUBMISSIONS.find((x) => x.key === key);
    if (s) setCode(s.code);
    setRun(null);
  }

  async function tryExamples() {
    setBusy("run");
    setError(null);
    try {
      setRun(await api(`/jobs/${job.id}/examples-run`, { body: { files: { "solution.py": code } } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function submit() {
    if (!window.confirm("Submit for grading? You get one graded submission for this job.")) return;
    setBusy("submit");
    setError(null);
    try {
      const r = await api<{ submission_id: string }>(`/jobs/${job.id}/submit`, { body: { files: { "solution.py": code } } });
      nav(`/submissions/${r.submission_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy("");
    }
  }

  const hint = SAMPLE_SUBMISSIONS.find((x) => x.key === pick)?.hint;
  return (
    <section className="panel workspace">
      <div className="workspace__head">
        <h2>Your solution</h2>
        <span className="muted">Due {new Date(deadline).toLocaleString()}</span>
      </div>
      <div className="samples" role="group" aria-label="Load a sample solution">
        <span className="muted small">Load a sample:</span>
        {SAMPLE_SUBMISSIONS.map((s) => (
          <button key={s.key} className={`chip ${pick === s.key ? "is-on" : ""} ${s.key.startsWith("cheat") ? "chip--cheat" : ""}`} onClick={() => load(s.key)}>
            {s.label}
          </button>
        ))}
      </div>
      {hint && <p className="muted small">{hint}</p>}
      <textarea
        className="editor mono"
        spellCheck={false}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder={"# solution.py\ndef solve(input: str) -> str:\n    ..."}
        aria-label="solution.py"
        rows={22}
      />
      <div className="row">
        <button className="btn btn--ghost" onClick={tryExamples} disabled={!code || !!busy}>{busy === "run" ? "Running…" : "Run the public examples"}</button>
        <button className="btn" onClick={submit} disabled={!code || !!busy}>{busy === "submit" ? "Submitting…" : "Submit for grading"}</button>
      </div>
      {run && (
        <div className="runs">
          <b className="num">{run.passed}/{run.total}</b> public examples passed
          <ul>{run.results.map((r) => <li key={r.id} className={r.passed ? "ok" : "bad"}><span className="mono">{r.id}</span> {r.passed ? "pass" : r.error ? `error: ${r.error}` : "wrong output"} <span className="muted num">{r.ms}ms</span></li>)}</ul>
          <p className="muted small">Hidden tests and fresh inputs are only run once you submit.</p>
        </div>
      )}
      <ErrorNote error={error} />
    </section>
  );
}
