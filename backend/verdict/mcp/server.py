"""MCP server so any agent can take Verdict jobs.

Tools: list_jobs, get_job, claim_job, run_examples, submit_work, get_verdict.
It is a thin client of the Verdict API, authenticated with an agent key (POST /agents), so the
agent acts for its PayPal-identified owner and every rule of the API still applies: one graded
submission, hidden tests never exposed, payment decided by the grader and not by the agent.

Run (stdio):
    VERDICT_API_URL=http://localhost:8000 VERDICT_AGENT_KEY=vk_... python -m verdict.mcp.server
"""

from __future__ import annotations

import os
from typing import Any

import httpx

INSTRUCTIONS = """Verdict pays for code only when it passes hidden tests.
1. list_jobs, then get_job to read the spec, the public examples and the test-group weights.
2. claim_job starts your deadline.
3. Write solution.py defining solve(input: str) -> str (standard library only).
4. run_examples as often as you like: it runs only the public examples.
5. submit_work ONCE. Grading runs hidden tests plus 200 fresh random inputs; hard-coded
   answers fail the fresh inputs and code that tampers with the grader is voided.
6. get_verdict until the job settles. Payment is the passing share of the budget, minus 5%."""


class VerdictAPIError(RuntimeError):
    pass


class VerdictAPI:
    """Small typed client. `client` can be any httpx.Client (tests pass FastAPI's TestClient)."""

    def __init__(self, base_url: str = "", key: str = "", client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=120)
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        r = self.http.request(method, path, headers=self.headers, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise VerdictAPIError(f"{method} {path} failed ({r.status_code}): {detail}")
        return r.json()

    def list_jobs(self) -> list[dict]:
        return [{"id": j["id"], "title": j["title"], "amount": j["amount"],
                 "currency": j["currency"], "min_score": j["min_score"],
                 "deadline_hours": j["deadline_hours"],
                 "groups": {g["name"]: g["weight"] for g in j["groups"]}}
                for j in self._call("GET", "/jobs")]

    def get_job(self, job_id: str) -> dict:
        j = self._call("GET", f"/jobs/{job_id}")
        return {k: j[k] for k in ("id", "title", "spec_md", "amount", "currency", "min_score",
                                  "deadline_hours", "groups", "examples", "suite_sha256",
                                  "state")}

    def claim(self, job_id: str) -> dict:
        return self._call("POST", f"/jobs/{job_id}/claim")

    def run_examples(self, job_id: str, code: str) -> dict:
        return self._call("POST", f"/jobs/{job_id}/examples-run",
                          json={"files": {"solution.py": code}})

    def submit(self, job_id: str, code: str) -> dict:
        return self._call("POST", f"/jobs/{job_id}/submit", json={"files": {"solution.py": code}})

    def verdict(self, submission_id: str) -> dict:
        v = self._call("GET", f"/submissions/{submission_id}")
        return {"job_state": v["job_state"], "runs": v["runs"], "verdict": v["verdict"],
                "ai_review": v.get("ai_review")}


def build_server(api: VerdictAPI):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("verdict", instructions=INSTRUCTIONS)

    @server.tool()
    def list_jobs() -> list[dict]:
        """Open jobs: id, title, budget, minimum score, deadline and test-group weights."""
        return api.list_jobs()

    @server.tool()
    def get_job(job_id: str) -> dict:
        """The full spec, public examples, group weights and the sealed suite hash."""
        return api.get_job(job_id)

    @server.tool()
    def claim_job(job_id: str) -> dict:
        """Claim an open job. Your deadline starts now; you get one graded submission."""
        return api.claim(job_id)

    @server.tool()
    def run_examples(job_id: str, code: str) -> dict:
        """Run solution.py (solve(input) -> str) on the PUBLIC examples only. Unlimited."""
        return api.run_examples(job_id, code)

    @server.tool()
    def submit_work(job_id: str, code: str) -> dict:
        """Submit solution.py for grading. ONE try per job: run_examples first."""
        return api.submit(job_id, code)

    @server.tool()
    def get_verdict(submission_id: str) -> dict:
        """Grading state, per-group scores and, once settled, the payment split."""
        return api.verdict(submission_id)

    return server


def main() -> None:
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)   # stdio server: keep stderr quiet
    key = os.environ.get("VERDICT_AGENT_KEY", "")
    if not key:
        raise SystemExit("set VERDICT_AGENT_KEY (create one with POST /agents)")
    api = VerdictAPI(os.environ.get("VERDICT_API_URL", "http://localhost:8000"), key)
    build_server(api).run("stdio")


if __name__ == "__main__":
    main()
