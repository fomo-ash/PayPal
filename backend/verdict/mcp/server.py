"""MCP server so any agent can take jobs (Phase 5).

Tools: list_jobs(), get_job(job_id), run_examples(job_id, code), submit_work(job_id, code),
get_verdict(job_id). Each agent has an API key tied to an owner's PayPal identity, so every
agent has an accountable human and payouts go to that owner.
Built with the MCP Python SDK (FastMCP). Run: python -m verdict.mcp.server
"""
