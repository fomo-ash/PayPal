"""Buyer-side fairness check at posting time (Phase 3), closing loophole B2.

For each hidden test, ask Claude Sonnet 5.5: "Is this input→output behaviour implied by the
spec and public examples?" Returns SpecCheckItem per test. Any implied_by_spec=false blocks
funding until the buyer edits the spec or removes the test. The buyer sees the reason.
"""
