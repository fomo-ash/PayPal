import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorNote, Field, NeedRole } from "../components";
import { api } from "../lib/api";
import { SAMPLE_SPEC, SAMPLE_SUITE_SIZE, SAMPLE_TITLE, sampleSuite } from "../lib/sample";
import type { Job } from "../lib/types";

export default function NewJob() {
  return (
    <NeedRole role="buyer">
      <Form />
    </NeedRole>
  );
}

function Form() {
  const nav = useNavigate();
  const [title, setTitle] = useState(SAMPLE_TITLE);
  const [amount, setAmount] = useState("100.00");
  const [minScore, setMinScore] = useState("50");
  const [hours, setHours] = useState("24");
  const [spec, setSpec] = useState(SAMPLE_SPEC);
  const [suite, setSuite] = useState<"sample" | "file">("sample");
  const [fileSuite, setFileSuite] = useState<unknown>(null);
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function readFile(f: File | undefined) {
    if (!f) return;
    try {
      setFileSuite(JSON.parse(await f.text()));
      setFileName(f.name);
      setError(null);
    } catch {
      setError("That file is not valid JSON.");
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = suite === "sample" ? sampleSuite() : fileSuite;
    if (!body) {
      setError("Choose a suite file, or use the sample suite.");
      return;
    }
    try {
      setBusy("Creating the job");
      const job = await api<Job>("/jobs", {
        body: {
          title, spec_md: spec, amount: Number(amount).toFixed(2),
          min_score: (Number(minScore) / 100).toFixed(2), deadline_hours: Number(hours),
        },
      });
      setBusy("Uploading the hidden tests");
      await api(`/jobs/${job.id}/suite`, { method: "PUT", body });
      nav(`/jobs/${job.id}?validate=1`);
    } catch (err) {
      setError((err as Error).message);
      setBusy("");
    }
  }

  return (
    <form className="narrow form" onSubmit={submit}>
      <h1>Post a job</h1>
      <p className="lede">
        Describe the work and attach hidden tests with a reference solution. Before any money is held, Verdict runs your
        reference on every test and asks an AI whether each test follows from your description.
      </p>

      <div className="grid2">
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={200} /></Field>
        <Field label="Budget (USD)" hint="PayPal holds this; you pay only the share that passes.">
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" pattern="\d+(\.\d{1,2})?" required />
        </Field>
        <Field label="Minimum score (%)" hint="Below this, nothing is captured.">
          <input value={minScore} onChange={(e) => setMinScore(e.target.value)} inputMode="numeric" pattern="\d{1,3}" required />
        </Field>
        <Field label="Time to deliver (hours)">
          <input value={hours} onChange={(e) => setHours(e.target.value)} inputMode="numeric" pattern="\d+" required />
        </Field>
      </div>

      <Field label="Description (Markdown)" hint="Workers see this and the public examples. Hidden tests must follow from it.">
        <textarea className="mono" rows={12} value={spec} onChange={(e) => setSpec(e.target.value)} required />
      </Field>

      <fieldset className="choice">
        <legend>Hidden tests</legend>
        <label className={`opt ${suite === "sample" ? "is-on" : ""}`}>
          <input type="radio" name="suite" checked={suite === "sample"} onChange={() => setSuite("sample")} />
          <span>
            <b>Sample suite for this description</b>
            <small>{SAMPLE_SUITE_SIZE.tests} hidden tests in {SAMPLE_SUITE_SIZE.groups} weighted groups, a reference solution, and a generator for 200 fresh inputs.</small>
          </span>
        </label>
        <label className={`opt ${suite === "file" ? "is-on" : ""}`}>
          <input type="radio" name="suite" checked={suite === "file"} onChange={() => setSuite("file")} />
          <span>
            <b>Upload my own</b>
            <small>JSON with <code>groups</code>, <code>fresh</code>, <code>tests</code>, <code>examples</code>, <code>reference</code> and optional <code>generator</code>.</small>
            {suite === "file" && (
              <input type="file" accept="application/json,.json" onChange={(e) => readFile(e.target.files?.[0])} />
            )}
            {fileName && <small className="mono">{fileName}</small>}
          </span>
        </label>
      </fieldset>

      <ErrorNote error={error} />
      <div className="row">
        <button className="btn" disabled={!!busy}>{busy ? `${busy}…` : "Create and check the tests"}</button>
      </div>
    </form>
  );
}
