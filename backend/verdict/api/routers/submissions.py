"""Submissions (Phase 2)
POST /jobs/{id}/examples-run     unlimited runs against PUBLIC examples only
POST /jobs/{id}/submit           the ONE graded submission → SUBMITTED, enqueue grading
GET  /submissions/{id}           status, group scores (failing hidden tests revealed after verdict)
GET  /submissions/{id}/code      buyer only, and only in state CODE_RELEASED
"""
