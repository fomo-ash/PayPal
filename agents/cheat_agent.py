"""Cheating agents: submit a bench cheat through the MCP server and watch it get caught.

    VERDICT_AGENT_KEY=vk_... python agents/cheat_agent.py cheat_memorizer [job_id]

Any folder under bench/tasks/log_parser/submissions works: cheat_memorizer (fresh inputs),
cheat_injection (grader injection), cheat_exit (harness tamper), cheat_env_sniff (hidden-test
probing), cheat_conftest (rejected file), cheat_timebomb (AI review → human).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from honest_agent import verdict_tools, wait_for_verdict

SUBS = Path(__file__).resolve().parents[1] / "bench" / "tasks" / "log_parser" / "submissions"


async def run(name: str, job_id: str | None) -> int:
    code = (SUBS / name / "solution.py").read_text()
    async with verdict_tools() as tool:
        jobs = await tool("list_jobs")
        if not jobs:
            print("no open jobs")
            return 1
        job_id = job_id or jobs[0]["id"]
        await tool("claim_job", job_id=job_id)
        try:
            sub = await tool("submit_work", job_id=job_id, code=code)
        except RuntimeError as e:          # rejected before grading (e.g. conftest.py)
            print(f"refused at submission: {e}")
            return 0
        print(f"{name} submitted as {sub['submission_id']}")
        await wait_for_verdict(tool, sub["submission_id"])
    return 0


def main() -> None:
    if len(sys.argv) < 2 or not (SUBS / sys.argv[1] / "solution.py").exists():
        raise SystemExit("usage: cheat_agent.py <bench submission folder> [job_id]")
    if not os.environ.get("VERDICT_AGENT_KEY"):
        raise SystemExit("set VERDICT_AGENT_KEY")
    sys.exit(anyio.run(run, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))


if __name__ == "__main__":
    main()
