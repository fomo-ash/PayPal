"""Request dependencies: DB session, current user, and the app's services.

Services (session factory, blob store, PayPal client, sandbox runner, LLM, task queue) live on
`app.state` so tests can build an app with fakes: `create_app(Services(...))`.

Auth: `Authorization: Bearer <token>` from Log in with PayPal (api/routers/auth.py).
DEV ONLY fallback: header `X-User-Id: <uuid>`, refused when DEV_AUTH is off or PAYPAL_ENV=live.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from verdict.api import sessions
from verdict.config import Settings
from verdict.db.models import Agent, User
from verdict.sandbox.runner import Runner
from verdict.storage import BlobStore


@dataclass
class Services:
    settings: Settings
    Session: sessionmaker  # noqa: N815 - a factory, named like a class
    store: BlobStore
    paypal: Any                                   # PayPalClient (or a fake in tests)
    runner: Runner
    enqueue_grading: Callable[[uuid.UUID], None]  # Celery .delay in prod, inline in tests
    llm: Any = None                               # judge.llm.LLMClient; None = AI not configured
    # run the outbox now for a job a reviewer just settled; the beat tick does it anyway
    kick_money: Callable[[uuid.UUID], None] = field(default=lambda job_id: None)


def services(request: Request) -> Services:
    return request.app.state.services


def db(svc: Annotated[Services, Depends(services)]) -> Iterator[Session]:
    """Endpoints call s.commit() themselves, so the commit happens before the response."""
    s = svc.Session()
    try:
        yield s
    finally:
        s.close()


def current_user(request: Request, s: Annotated[Session, Depends(db)],
                 svc: Annotated[Services, Depends(services)],
                 authorization: Annotated[str | None, Header()] = None,
                 x_user_id: Annotated[str | None, Header()] = None) -> User:
    request.state.agent_id = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() == "bearer" and token.startswith("vk_"):
            return _agent_owner(request, s, token)
        body = (sessions.read(svc.settings.session_secret, "session", token)
                if scheme.lower() == "bearer" else None)
        user = s.get(User, uuid.UUID(body["u"])) if body else None
        if user is None:
            raise HTTPException(401, "session expired; log in with PayPal again")
        return user
    if not svc.settings.dev_auth or svc.settings.paypal_env == "live":
        raise HTTPException(401, "login required")
    if not x_user_id:
        raise HTTPException(401, "missing X-User-Id header (dev auth)")
    try:
        uid = uuid.UUID(x_user_id)
    except ValueError as e:
        raise HTTPException(401, "bad X-User-Id") from e
    user = s.get(User, uid)
    if user is None:
        raise HTTPException(401, "unknown user")
    return user


def _agent_owner(request: Request, s: Session, key: str) -> User:
    agent = s.scalar(select(Agent).where(
        Agent.api_key_hash == hashlib.sha256(key.encode()).hexdigest()))
    owner = s.get(User, agent.owner_user_id) if agent else None
    if agent is None or owner is None:
        raise HTTPException(401, "unknown agent key")
    request.state.agent_id = agent.id
    return owner


DB = Annotated[Session, Depends(db)]
CurrentUser = Annotated[User, Depends(current_user)]
Svc = Annotated[Services, Depends(services)]
