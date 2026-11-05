"""Request dependencies: DB session, current user, and the app's services.

Services (session factory, blob store, PayPal client, sandbox runner, task queue) live on
`app.state` so tests can build an app with fakes: `create_app(Services(...))`.

Auth (until Log in with PayPal lands in Phase 4): DEV ONLY header `X-User-Id: <uuid>`.
It is refused outright when PAYPAL_ENV=live.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from verdict.config import Settings
from verdict.db.models import User
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


def services(request: Request) -> Services:
    return request.app.state.services


def db(svc: Annotated[Services, Depends(services)]) -> Iterator[Session]:
    """Endpoints call s.commit() themselves, so the commit happens before the response."""
    s = svc.Session()
    try:
        yield s
    finally:
        s.close()


def current_user(s: Annotated[Session, Depends(db)],
                 svc: Annotated[Services, Depends(services)],
                 x_user_id: Annotated[str | None, Header()] = None) -> User:
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


DB = Annotated[Session, Depends(db)]
CurrentUser = Annotated[User, Depends(current_user)]
Svc = Annotated[Services, Depends(services)]
