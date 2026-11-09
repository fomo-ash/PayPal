import { useEffect, useState } from "react";
import { ErrorNote } from "../components";
import { api } from "../lib/api";

interface Result { valid: boolean; key_id: string; signed_by_this_key: boolean; job_id: string | null }

export default function Verify() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [key, setKey] = useState<{ public_key: string; key_id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api("/receipts/public-key").then(setKey).catch(() => setKey(null));
  }, []);

  async function check() {
    setError(null);
    setResult(null);
    let doc: unknown;
    try {
      doc = JSON.parse(text);
    } catch {
      setError("Paste the whole receipt JSON (it has \"receipt\" and \"signature\").");
      return;
    }
    try {
      setResult(await api<Result>("/receipts/verify", { body: doc }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function loadFile(f: File | undefined) {
    if (f) setText(await f.text());
  }

  return (
    <section className="narrow">
      <h1>Verify a receipt</h1>
      <p className="lede">
        Every settled job gets a receipt signed with Ed25519 over canonical JSON: the PayPal IDs, the scores, the decision and the
        head of the job's hash-chained audit log. No login needed.
      </p>
      {key && (
        <p className="muted small">Verdict public key <span className="mono">{key.key_id}</span>: <span className="mono wrap">{key.public_key}</span></p>
      )}
      <textarea className="mono" rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder='{"receipt": {...}, "signature": "..."}' aria-label="Receipt JSON" />
      <div className="row">
        <button className="btn" onClick={check} disabled={!text.trim()}>Verify</button>
        <label className="btn btn--ghost">
          Open a file
          <input type="file" accept="application/json,.json" hidden onChange={(e) => loadFile(e.target.files?.[0])} />
        </label>
      </div>
      <ErrorNote error={error} />
      {result && (
        <p className={`note ${result.valid ? "note--ok" : "note--err"}`}>
          {result.valid
            ? <>Valid. Signed by key <span className="mono">{result.key_id}</span> and not changed since. Job <span className="mono">{result.job_id}</span>.</>
            : result.signed_by_this_key ? "Invalid: the receipt was changed after it was signed." : "Invalid: not signed by this server's key."}
        </p>
      )}
    </section>
  );
}
