"""POST /webhooks/paypal: verify signature → store → dedupe → audit (see paypal/webhooks.py)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from verdict.api.deps import DB, Services, Svc
from verdict.paypal.client import PayPalError
from verdict.paypal.webhooks import BadEvent, record_event

router = APIRouter(tags=["webhooks"])
MAX_BODY = 256_000


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, s: DB, svc: Svc) -> dict:
    if svc.paypal is None or not svc.settings.paypal_webhook_id:
        raise HTTPException(503, "webhooks are not configured")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "event too large")
    try:
        event = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, "not JSON") from e
    if not isinstance(event, dict):
        raise HTTPException(400, "not an event")
    # PayPal and DB calls are blocking: run them off the event loop
    return await run_in_threadpool(_handle, s, svc, dict(request.headers), event)


def _handle(s: Session, svc: Services, headers: dict[str, str], event: dict) -> dict:
    try:
        ok = svc.paypal.verify_webhook_signature(headers=headers, event=event,
                                                 webhook_id=svc.settings.paypal_webhook_id)
    except PayPalError as e:
        raise HTTPException(502, "could not verify the event with PayPal") from e
    if not ok:
        raise HTTPException(400, "signature verification failed")
    try:
        result = record_event(s, event)
    except BadEvent as e:
        raise HTTPException(400, str(e)) from e
    s.commit()
    return {"result": result}
