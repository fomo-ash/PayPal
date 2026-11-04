"""Dispute evidence (Phase 5, stretch).

On CUSTOMER.DISPUTE.CREATED: build the evidence pack (job spec, sealed suite hash, test results,
AI findings, delivery timestamp, signed receipt PDF) and submit it with
POST /v1/customer/disputes/{id}/provide-evidence (multipart: JSON + files).
"""
