"""MCP server: tools wrap the API with the agent's key; the stdio server really starts."""

import os
import sys
from pathlib import Path

import anyio
import pytest
from conftest import bench_files

from verdict.mcp.server import VerdictAPI, VerdictAPIError, build_server

TOOLS = {"list_jobs", "get_job", "claim_job", "run_examples", "submit_work", "get_verdict"}


@pytest.fixture
def agent_api(api, user):
    owner = user("worker", email="owner@example.com", paypal_payer_id="OWNERPAYER1")
    key = api.post("/agents", json={"name": "mcp"}, headers=owner).json()["api_key"]
    return VerdictAPI(key=key, client=api)


def test_tools_cover_the_whole_worker_flow(agent_api, open_job):
    _, job_id = open_job()
    jobs = agent_api.list_jobs()
    assert [j["id"] for j in jobs] == [job_id] and jobs[0]["groups"]["core"] == "0.6000"
    job = agent_api.get_job(job_id)
    assert job["examples"] and "tests" not in job and job["suite_sha256"]
    agent_api.claim(job_id)
    code = bench_files("honest_full")["files"]["solution.py"]
    ex = agent_api.run_examples(job_id, code)
    assert ex["passed"] == ex["total"] > 0
    sub = agent_api.submit(job_id, code)
    v = agent_api.verdict(sub["submission_id"])
    assert v["job_state"] == "SUBMITTED" and v["verdict"] is None


def test_api_errors_become_tool_errors(agent_api, open_job):
    _, job_id = open_job()
    with pytest.raises(VerdictAPIError, match="do not hold an active claim"):
        agent_api.run_examples(job_id, "def solve(x): return x")


def test_server_exposes_six_tools(agent_api):
    server = build_server(agent_api)
    names = {t.name for t in anyio.run(server.list_tools)}
    assert names == TOOLS


def test_stdio_server_starts_and_lists_tools():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    backend = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "verdict.mcp.server"],
        env={**os.environ, "PYTHONPATH": str(backend), "VERDICT_AGENT_KEY": "vk_test",
             "VERDICT_API_URL": "http://127.0.0.1:9"})

    async def go():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            return {t.name for t in (await s.list_tools()).tools}

    assert anyio.run(go) == TOOLS
