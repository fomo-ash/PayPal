export type Role = "buyer" | "worker" | "admin";

export interface User {
  id: string;
  role: Role;
  email: string | null;
  display_name: string;
  has_paypal: boolean;
}

export interface PublicConfig {
  paypal_client_id: string;
  paypal_env: string;
  demo_login: boolean;
  paypal_login: boolean;
}

export interface Group {
  name: string;
  weight: string;
  tests: number;
  fresh_inputs: number;
}

export interface Job {
  id: string;
  title: string;
  spec_md: string;
  state: string;
  amount: string;
  currency: string;
  min_score: string;
  fee_bps: number;
  deadline_hours: number;
  groups: Group[];
  examples: { input: string; expected: string }[];
  suite_sha256: string | null;
  spec_checked: boolean;
  created_at: string;
  validated?: boolean;
  paypal_order_id?: string | null;
  honor_expires_at?: string | null;
}

export interface SpecItem {
  test_id: string;
  implied: boolean;
  reason: string;
}

export interface ValidateResult {
  state: string;
  problems: string[];
  warnings: string[];
  spec_check: SpecItem[];
}

export interface Finding {
  file: string;
  line: number;
  category?: string;
  evidence?: string;
}

export interface VerdictDecision {
  score: string;
  raw_score: string;
  capture: string;
  fee: string;
  worker_amount: string;
  released: string;
  settlement: string;
  reason: string;
  decided_by: string;
}

export interface SubmissionView {
  id: string;
  job_id: string;
  job_state: string;
  sha256: string;
  submitted_at: string;
  runs: { kind: string; group: string; passed: number; total: number; flaky: string[] }[];
  verdict: VerdictDecision | null;
  scan_findings: { rule: string; file: string; line: number; message: string; hard_signal: boolean }[];
  ai_review: { decision: string; model: string; findings: Finding[]; explanation: string } | null;
}

export interface Receipt {
  receipt: {
    job: { id: string; title: string; amount: string; currency: string; state: string };
    suite_sha256: string;
    submission_sha256: string | null;
    decision: { settlement: string; score: string; capture: string; fee: string; worker: string; released: string; decided_by: string; reason: string } | null;
    paypal: { order_id: string | null; authorization_id: string | null; capture_id: string | null; payout_batch_id: string | null };
    audit_head_hash: string;
    issued_at: string;
    key_id: string;
    [k: string]: unknown;
  };
  signature: string;
}
