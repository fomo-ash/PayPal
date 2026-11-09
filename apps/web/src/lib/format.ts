export function usd(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return `$${n.toFixed(2)}`;
}

export function pct(v: string | number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || v === "") return "—";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

export function short(id: string | null | undefined, n = 8): string {
  return id ? id.slice(0, n) : "—";
}

// What each job state means to a person looking at it.
export const STATE_LABEL: Record<string, string> = {
  DRAFT: "Draft",
  VALIDATING: "Checking the tests",
  INVALID: "Tests need fixing",
  AWAITING_FUNDS: "Ready to fund",
  FUNDED: "Funded",
  OPEN: "Open for workers",
  CLAIMED: "Claimed",
  SUBMITTED: "Submitted",
  GRADING: "Grading in the sandbox",
  JUDGING: "AI review",
  HUMAN_REVIEW: "Waiting for a reviewer",
  CAPTURING: "PayPal capturing",
  PAYING_OUT: "Paying the worker",
  PAYOUT_FAILED: "Payout failed",
  PAID: "Paid",
  CODE_RELEASED: "Paid, code delivered",
  VOIDING: "PayPal voiding the hold",
  VOIDED: "Voided, buyer keeps everything",
  CANCELLED: "Cancelled",
};

export const SETTLED = new Set(["PAID", "CODE_RELEASED", "VOIDED", "PAYOUT_FAILED"]);
export const MOVING = new Set(["SUBMITTED", "GRADING", "JUDGING", "CAPTURING", "PAYING_OUT", "VOIDING"]);

export function tone(state: string): "paid" | "void" | "wait" | "idle" {
  if (state === "PAID" || state === "CODE_RELEASED") return "paid";
  if (state === "VOIDED" || state === "VOIDING" || state === "INVALID" || state === "PAYOUT_FAILED") return "void";
  if (MOVING.has(state) || state === "HUMAN_REVIEW" || state === "CLAIMED") return "wait";
  return "idle";
}
