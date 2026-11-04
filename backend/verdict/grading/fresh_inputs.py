"""Fresh-input generators (Phase 2).

The buyer uploads gen_input(rng) -> str, or the cheap draft model (llama-3.1-8b-instant on
Groq) drafts one from the spec and examples.
A generator is accepted only if the reference solution runs on N generated inputs without
error and the inputs are diverse (distinct-output ratio above a threshold).

Lesson from the bench: keep inputs SMALL. Long inputs contain every feature at once, so one
missing rule fails almost every input and honest partial work earns nothing.
"""
