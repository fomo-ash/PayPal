"""Honest worker agent (Phase 5).

Loop: list_jobs → get_job → draft solve() with Claude Sonnet 5.5 → run_examples → fix → submit_work
→ poll get_verdict. Uses the Verdict MCP server; the agent's API key is tied to its owner's
PayPal identity, so the payout lands in the owner's sandbox account.
"""
