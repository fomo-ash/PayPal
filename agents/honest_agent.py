"""Honest worker agent: an LLM that takes a Verdict job over MCP and solves it.

Loop: list_jobs → get_job → claim_job → draft solve() with the free judge LLM → run_examples
→ fix from the failures (up to 3 drafts) → submit_work once → poll get_verdict.
The agent key ties it to its owner's PayPal identity, so the payout lands with the owner.

Run (API up, e.g. `make local`):
    VERDICT_AGENT_KEY=vk_... python agents/honest_agent.py [job_id]
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from verdict.config import get_settings  # noqa: E402
from verdict.judge.llm import LLMClient, client_from_settings  # noqa: E402

MAX_DRAFTS = 3
DONE = {"PAID", "CODE_RELEASED", "VOIDED", "HUMAN_REVIEW", "PAYOUT_FAILED"}
SYSTEM = ("You are a careful Python engineer. You write correct, general solutions from a "
          "specification, never answers hard-coded for particular inputs. Reply with one JSON "
          "object only.")


class Draft(BaseModel):
    code: str = Field(min_length=10)
    notes: str = ""


def prompt(job: dict, feedback: str) -> str:
    examples = json.dumps(job["examples"][:8], indent=1)[:6000]
    return (f"Write solution.py for this paid job. It must define solve(input: str) -> str, use "
            f"only the Python standard library, and must not read files, the network or the "
            f"environment. Hidden tests and 200 random inputs will grade it, so handle the "
            f"spec in general.\n\n<spec>\n{job['spec_md']}\n</spec>\n\n<public_examples>\n"
            f"{examples}\n</public_examples>\n{feedback}\n"
            'Reply as {"code": "<full solution.py>", "notes": "<one line>"}.')


def failures(run: dict) -> str:
    bad = [r for r in run["results"] if not r["passed"]][:4]
    if not bad:
        return ""
    lines = [f"- {r['id']}: got {r['output'][:400]!r}" + (f", error {r['error']}" if r["error"]
                                                            else "") for r in bad]
    return ("\nYour previous draft failed these public examples (compare with the expected "
            "output above):\n" + "\n".join(lines) + "\n")


def write_code(llm: LLMClient, job: dict, feedback: str) -> str:
    res = llm.chat_json(SYSTEM, prompt(job, feedback), Draft, temperature=0.2, max_tokens=4000)
    return res.data.code  # type: ignore[attr-defined]


@asynccontextmanager
async def verdict_tools() -> AsyncIterator[Callable[..., Awaitable[Any]]]:
    """Start the Verdict MCP server over stdio and yield `tool(name, **args)`."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "verdict.mcp.server"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend")})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        async def tool(name: str, **args: Any) -> Any:
            res = await session.call_tool(name, args)
            text = "".join(getattr(c, "text", "") for c in res.content)
            if res.is_error:
                raise RuntimeError(f"{name}: {text}")
            data = res.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                data = data["result"]
            return data if data is not None else json.loads(text)

        yield tool


async def wait_for_verdict(tool: Callable[..., Awaitable[Any]], sid: str) -> dict:
    last, v = None, {}
    for _ in range(150):
        v = await tool("get_verdict", submission_id=sid)
        if v["job_state"] != last:
            last = v["job_state"]
            print(f"  {time.strftime('%H:%M:%S')}  {last}")
        if last in DONE or (v["verdict"] or {}).get("settlement") == "VOID":
            break                  # a VOID verdict pays $0 whatever PayPal does next
        await anyio.sleep(4)
    for r in v["runs"]:
        print(f"  {r['kind']:6} {r['group']:5} {r['passed']}/{r['total']}")
    if v.get("ai_review"):
        print(f"  AI review: {v['ai_review']['decision']}")
    if v["verdict"]:
        d = v["verdict"]
        print(f"  {d['settlement']} · score {float(d['score']):.1%} · "
              f"worker ${d['worker_amount']} · {d['reason']}")
    return v


async def run(job_id: str | None) -> int:
    llm = client_from_settings(get_settings())
    async with verdict_tools() as tool:
        jobs = await tool("list_jobs")
        if not jobs:
            print("no open jobs")
            return 1
        job_id = job_id or jobs[0]["id"]
        job = await tool("get_job", job_id=job_id)
        print(f"job {job_id}: {job['title']} · ${job['amount']} · min score {job['min_score']}")
        await tool("claim_job", job_id=job_id)
        print("claimed")

        code, feedback, best = "", "", (-1, "")
        for n in range(1, MAX_DRAFTS + 1):
            code = await anyio.to_thread.run_sync(write_code, llm, job, feedback)
            ex = await tool("run_examples", job_id=job_id, code=code)
            print(f"draft {n}: examples {ex['passed']}/{ex['total']}")
            if ex["passed"] > best[0]:
                best = (ex["passed"], code)
            if ex["passed"] == ex["total"]:
                break
            feedback = failures(ex)
        code = best[1]

        sub = await tool("submit_work", job_id=job_id, code=code)
        sid = sub["submission_id"]
        print(f"submitted {sid}; grading (hidden tests + fresh inputs)…")
        await wait_for_verdict(tool, sid)
        return 0

def main() -> None:
    if not os.environ.get("VERDICT_AGENT_KEY"):
        raise SystemExit("set VERDICT_AGENT_KEY (POST /agents as a worker logged in with PayPal)")
    sys.exit(anyio.run(run, sys.argv[1] if len(sys.argv) > 1 else None))


if __name__ == "__main__":
    main()
