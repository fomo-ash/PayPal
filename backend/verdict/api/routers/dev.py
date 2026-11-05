"""DEV ONLY: create users to act as with the X-User-Id header. Mounted only when DEV_AUTH=true.
Replaced by Log in with PayPal (Phase 4)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from verdict.api.deps import DB
from verdict.db.models import User

router = APIRouter(prefix="/dev", tags=["dev"])


class NewUser(BaseModel):
    role: Literal["buyer", "worker", "admin"]
    email: str | None = Field(default=None, max_length=254)
    display_name: str = Field(default="", max_length=80)
    paypal_payer_id: str | None = Field(default=None, max_length=32)


@router.post("/users", status_code=201)
def create_user(body: NewUser, s: DB) -> dict:
    user = User(role=body.role, email=body.email, display_name=body.display_name,
                paypal_payer_id=body.paypal_payer_id)
    s.add(user)
    s.commit()
    return {"id": str(user.id), "role": user.role}
