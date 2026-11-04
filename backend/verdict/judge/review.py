"""AI cheating review (Phase 3).

Input (everything wrapped as untrusted DATA inside clearly delimited tags):
  spec, group scores, hidden-vs-fresh pass gap, scanner findings, the submitted code with line numbers.
Output: judge.schema.Review via tool use with a strict JSON schema.
The result feeds verdict.core.policy.decide() as an AIDecision enum ONLY.
Every call is traced in Langfuse; prompt + response stored with the verdict.
"""
