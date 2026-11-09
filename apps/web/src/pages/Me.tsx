import type { ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorNote, Spinner } from "../components";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATE_LABEL, usd } from "../lib/format";
import type { Job } from "../lib/types";

interface Work { job_id: string; title: string; amount: string; job_state: string; claim_status: string; deadline_at: string; submission_id: string | null; via_agent: boolean }

const stateCol = { headerName: "State", width: 230, valueFormatter: (p: { value: string }) => STATE_LABEL[p.value] ?? p.value };

export default function Me() {
  const { user, ready } = useAuth();
  if (!ready) return <Spinner label="Loading" />;
  if (!user) return <div className="empty"><h2>Log in first</h2><Link className="btn" to="/login">Log in</Link></div>;
  return user.role === "buyer" ? <BuyerJobs /> : <WorkerJobs />;
}

function BuyerJobs() {
  const nav = useNavigate();
  const [rows, setRows] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Job[]>("/jobs/mine").then(setRows).catch((e) => setError(e.message)); }, []);
  const cols = useMemo<ColDef<Job>[]>(() => [
    { field: "title", headerName: "Job", flex: 2, minWidth: 220 },
    { field: "amount", headerName: "Hold", width: 110, valueFormatter: (p) => usd(p.value), cellClass: "num" },
    { field: "state", ...stateCol },
    { field: "created_at", headerName: "Posted", width: 180, valueFormatter: (p) => new Date(p.value).toLocaleString() },
  ], []);
  return (
    <section>
      <div className="block__head row--between">
        <h1>My jobs</h1>
        <Link className="btn" to="/jobs/new">Post a job</Link>
      </div>
      <ErrorNote error={error} />
      {rows && rows.length === 0 && <p className="muted">No jobs yet.</p>}
      {rows && rows.length > 0 && (
        <div className="ag-theme-quartz grid" style={{ height: Math.min(80 + rows.length * 44, 520) }}>
          <AgGridReact<Job> rowData={rows} columnDefs={cols} rowClass="clickable" suppressCellFocus onRowClicked={(e) => e.data && nav(`/jobs/${e.data.id}`)} />
        </div>
      )}
    </section>
  );
}

function WorkerJobs() {
  const nav = useNavigate();
  const [rows, setRows] = useState<Work[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Work[]>("/submissions/mine").then(setRows).catch((e) => setError(e.message)); }, []);
  const cols = useMemo<ColDef<Work>[]>(() => [
    { field: "title", headerName: "Job", flex: 2, minWidth: 220 },
    { field: "amount", headerName: "Hold", width: 110, valueFormatter: (p) => usd(p.value), cellClass: "num" },
    { field: "job_state", ...stateCol },
    { field: "via_agent", headerName: "By", width: 110, valueFormatter: (p) => (p.value ? "AI agent" : "you") },
    { field: "deadline_at", headerName: "Due", width: 180, valueFormatter: (p) => new Date(p.value).toLocaleString() },
  ], []);
  return (
    <section>
      <div className="block__head">
        <h1>My work</h1>
        <p className="muted">Jobs you or your AI agents took. Agents use an API key and the MCP server; see the repo's agents/README.</p>
      </div>
      <ErrorNote error={error} />
      {rows && rows.length === 0 && <p className="muted">Nothing yet. <Link to="/">Pick an open job.</Link></p>}
      {rows && rows.length > 0 && (
        <div className="ag-theme-quartz grid" style={{ height: Math.min(80 + rows.length * 44, 520) }}>
          <AgGridReact<Work> rowData={rows} columnDefs={cols} rowClass="clickable" suppressCellFocus
            onRowClicked={(e) => e.data && nav(e.data.submission_id ? `/submissions/${e.data.submission_id}` : `/jobs/${e.data.job_id}`)} />
        </div>
      )}
    </section>
  );
}
