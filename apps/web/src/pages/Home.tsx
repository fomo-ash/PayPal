import type { ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorNote } from "../components";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { pct, usd } from "../lib/format";
import type { Job } from "../lib/types";

export default function Home() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Job[]>("/jobs").then(setJobs).catch((e) => setError(e.message));
  }, []);

  const cols = useMemo<ColDef<Job>[]>(() => [
    { field: "title", headerName: "Job", flex: 2, minWidth: 220 },
    { field: "amount", headerName: "Hold", width: 110, valueFormatter: (p) => usd(p.value), cellClass: "num" },
    { field: "min_score", headerName: "Min score", width: 120, valueFormatter: (p) => pct(p.value, 0), cellClass: "num" },
    {
      headerName: "Tests", width: 150,
      valueGetter: (p) => p.data ? `${p.data.groups.reduce((a, g) => a + g.tests, 0)} hidden · ${p.data.groups.reduce((a, g) => a + g.fresh_inputs, 0)} fresh` : "",
    },
    { field: "deadline_hours", headerName: "Time", width: 90, valueFormatter: (p) => `${p.value}h` },
    { field: "suite_sha256", headerName: "Sealed suite", flex: 1, minWidth: 140, valueFormatter: (p) => p.value ? `${String(p.value).slice(0, 12)}…` : "—", cellClass: "mono" },
  ], []);

  return (
    <>
      <section className="intro">
        <div>
          <p className="eyebrow">Pay-on-verification, on PayPal</p>
          <h1>Pay only for the code that passes.</h1>
          <p className="lede">
            The buyer's money is held by PayPal, not charged. Hidden tests and 200 fresh inputs grade the work in a sandbox,
            an AI looks for cheating, and PayPal captures exactly the share that passed. The rest goes back.
          </p>
          <div className="row">
            {!user && <Link className="btn" to="/login">Try it as a buyer, worker or reviewer</Link>}
            {user?.role === "buyer" && <Link className="btn" to="/jobs/new">Post a job</Link>}
            {user?.role === "worker" && <a className="btn" href="#open">Pick a job below</a>}
            {user?.role === "admin" && <Link className="btn" to="/review">Open the review queue</Link>}
            <a className="btn btn--ghost" href="https://verdict-site.onrender.com">How it works</a>
          </div>
        </div>
        <ol className="flow" aria-label="How one job moves">
          <li><b>Hold</b><span>PayPal authorizes the budget. Nothing is charged.</span></li>
          <li><b>Test</b><span>Hidden tests plus fresh inputs, in an isolated sandbox.</span></li>
          <li><b>Judge</b><span>AI review cites lines. It can only send a case to a person.</span></li>
          <li><b>Settle</b><span>Partial capture, void the rest, pay the worker.</span></li>
          <li><b>Proof</b><span>A signed receipt anyone can verify.</span></li>
        </ol>
      </section>

      <section id="open" className="block">
        <div className="block__head">
          <h2>Open jobs</h2>
          <p className="muted">Funded and waiting for a worker. A person or an AI agent (over MCP) can take one.</p>
        </div>
        <ErrorNote error={error} />
        {jobs && jobs.length === 0 && (
          <div className="empty empty--inline">
            <p>No open jobs right now.</p>
            {user?.role === "buyer" ? <Link className="btn btn--sm" to="/jobs/new">Post the first one</Link>
              : <Link className="btn btn--sm" to="/login?as=buyer">Post one as a buyer</Link>}
          </div>
        )}
        {jobs && jobs.length > 0 && (
          <div className="ag-theme-quartz grid" style={{ height: Math.min(80 + jobs.length * 44, 480) }}>
            <AgGridReact<Job>
              rowData={jobs}
              columnDefs={cols}
              onRowClicked={(e) => e.data && nav(`/jobs/${e.data.id}`)}
              rowClass="clickable"
              suppressCellFocus
            />
          </div>
        )}
      </section>
    </>
  );
}
