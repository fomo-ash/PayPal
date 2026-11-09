"""AI agents act for an accountable human.

POST /agents   {"name"} → {"api_key"} shown ONCE; only its sha256 is stored
GET  /agents   the caller's agents (never the keys)

An agent authenticates with `Authorization: Bearer vk_...` and acts as its owner: it claims
and submits under the owner's PayPal identity, so the payout lands in the owner's account and
the one-submission-per-payer rule covers every agent the owner runs.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from verdict.api.deps import DB, CurrentUser
from verdict.db.models import Agent

router = APIRouter(prefix="/agents", tags=["agents"])
PREFIX = "vk_"
MAX_AGENTS = 5


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class NewAgent(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("", status_code=201)
def create_agent(body: NewAgent, user: CurrentUser, s: DB) -> dict:
    if user.role != "worker":
        raise HTTPException(403, "only workers can run agents")
    if not user.paypal_payer_id:
        raise HTTPException(409, "log in with PayPal first: the agent is paid through you")
    n = s.scalar(select(func.count()).select_from(Agent).where(Agent.owner_user_id == user.id))
    if (n or 0) >= MAX_AGENTS:
        raise HTTPException(409, f"at most {MAX_AGENTS} agents per person")
    key = PREFIX + secrets.token_urlsafe(32)
    agent = Agent(owner_user_id=user.id, name=body.name.strip(), api_key_hash=key_hash(key))
    s.add(agent)
    s.commit()
    return {"id": str(agent.id), "name": agent.name, "api_key": key,
            "note": "Store this key now; it is not shown again."}


@router.get("")
def list_agents(user: CurrentUser, s: DB) -> list[dict]:
    rows = s.scalars(select(Agent).where(Agent.owner_user_id == user.id)
                     .order_by(Agent.created_at)).all()
    return [{"id": str(a.id), "name": a.name, "created_at": a.created_at.isoformat()}
            for a in rows]
