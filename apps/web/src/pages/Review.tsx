import type { ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CodeView, ErrorNote, NeedRole, Spinner } from "../components";
import { api } from "../lib/api";
import { pct, usd } from "../lib/format";
import type { SubmissionView } from "../lib/types";

interface Row { job_id: string; title: string; amount: string; max_capture: string; score: string; reason: string; submission_id: string; since: string }
interface Case { job: { id: string; title: string; spec_md: string; amount: string; state: string }; max_capture: string; submission: SubmissionView; code: Record<string, string> }

export default function Review() {
  return (
    <NeedRole role="admin">
      <Queue />
    </NeedRole>
  );
}

function Queue() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Row[]>("/admin/reviews").then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const cols = useMemo<ColDef<Row>[]>(() => [
    { field: "title", headerName: "Job", flex: 2, minWidth: 200 },
    { field: "score", headerName: "Score", width: 100, valueFormatter: (p) => pct(p.value), cellClass: "num" },
    { field: "max_capture", headerName: "Max you can approve", width: 180, valueFormatter: (p) => usd(p.value), cellClass: "num" },
    { field: "amount", headerName: "Hold", width: 100, valueFormatter: (p) => usd(p.value), cellClass: "num" },
    { field: "reason", headerName: "Why it is here", flex: 3, minWidth: 260, tooltipField: "reason" },
    { field: "since", headerName: "Waiting since", width: 170, valueFormatter: (p) => new Date(p.value).toLocaleString() },
  ], []);

  return (
    <section>
      <div className="block__head">
        <h1>Review queue</h1>
        <p className="muted">Cases the AI flagged without a hard signal. The PayPal hold stays in place until you decide. You can approve up to the scored amount, lower it, or void. Never more.</p>
      </div>
      <ErrorNote error={error} />
      {rows && rows.length === 0 && (
        <div className="empty empty--inline">
          <p>Nothing to review. A submission like the "hidden time bomb" sample lands here.</p>
        </div>
      )}
      {rows && rows.length > 0 && (
        <div className="ag-theme-quartz grid" style={{ height: Math.min(80 + rows.length * 44, 360) }}>
          <AgGridReact<Row> rowData={rows} columnDefs={cols} rowClass="clickable" suppressCellFocus
            onRowClicked={(e) => e.data && setOpen(e.data.job_id)} />
        </div>
      )}
      {open && <CaseView key={open} jobId={open} onDone={() => { setOpen(null); load(); }} />}
    </section>
  );
}

function CaseView({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const [c, setC] = useState<Case | null>(null);
  const [amount, setAmount] = useState("0");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api<Case>(`/admin/reviews/${jobId}`).then((x) => { setC(x); setAmount("0"); }).catch((e) => setError(e.message));
  }, [jobId]);

  async function decide(capture: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ settlement: string; capture: string }>(`/admin/reviews/${jobId}`, { body: { capture, note } });
      setDone(r.settlement === "VOID" ? "Voided. PayPal releases the whole hold to the buyer." : `Approved ${usd(r.capture)}. PayPal captures it and pays the worker.`);
      window.setTimeout(onDone, 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !c) return <ErrorNote error={error} />;
  if (!c) return <Spinner label="Loading the case" />;
  const ai = c.submission.ai_review;
  const findings = [...(ai?.findings ?? []), ...c.submission.scan_findings.map((f) => ({ file: f.file, line: f.line, category: f.rule, evidence: f.message }))];
  return (
    <section className="panel case">
      <h2>{c.job.title}</h2>
      {ai && (
        <div className="ai ai--flag">
          <p><span className="tag">AI review</span> <b>{ai.decision.replaceAll("_", " ").toLowerCase()}</b></p>
          <p>{ai.explanation}</p>
          <ul className="findings">{ai.findings.map((f, i) => <li key={i}><span className="mono">{f.file}:{f.line}</span> <b>{f.category?.replaceAll("_", " ")}</b> {f.evidence}</li>)}</ul>
        </div>
      )}
      <CodeView files={c.code} findings={findings} />
      {done ? <p className="note note--ok">{done}</p> : (
        <div className="decide">
          <label className="field">
            <span className="field__label">Capture (max {usd(c.max_capture)})</span>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
          </label>
          <label className="field">
            <span className="field__label">Note (kept in the audit log)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
          </label>
          <div className="row">
            <button className="btn btn--void" disabled={busy} onClick={() => decide("0")}>Void: buyer keeps everything</button>
            <button className="btn" disabled={busy || Number(amount) <= 0} onClick={() => decide(amount)}>Approve {usd(amount)}</button>
          </div>
          <ErrorNote error={error} />
        </div>
      )}
    </section>
  );
}
