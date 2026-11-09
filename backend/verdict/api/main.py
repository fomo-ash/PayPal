"""FastAPI app.

`create_app(services)` builds the app around injected services (tests pass fakes);
`app` is the production instance used by uvicorn, built lazily from settings.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from verdict.api.deps import CurrentUser, Services
from verdict.api.routers import (
    admin,
    agents,
    auth,
    demo,
    dev,
    jobs,
    receipts,
    submissions,
    webhooks,
)
from verdict.config import Settings, get_settings
from verdict.core.policy import ReviewError
from verdict.core.state_machine import IllegalTransition
from verdict.db.repo import StaleState
from verdict.grading.suite import SuiteError
from verdict.worker.money import MoneyError


def create_app(services: Services | None = None) -> FastAPI:
    app = FastAPI(title="Verdict API", version="0.1.0")
    app.state.services = services or default_services(get_settings())
    app.add_middleware(
        CORSMiddleware, allow_origins=app.state.services.settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT"], allow_credentials=False,
        allow_headers=["Authorization", "Content-Type", "X-User-Id"])

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/public-config")
    def public_config() -> dict:
        """What a browser may know: the PayPal client id is public by design (never the secret)."""
        cfg = app.state.services.settings
        return {"paypal_client_id": cfg.paypal_client_id, "paypal_env": cfg.paypal_env,
                "demo_login": cfg.demo_login and cfg.paypal_env != "live",
                "paypal_login": bool(cfg.paypal_login_enabled and cfg.session_secret
                                     and cfg.paypal_client_id)}

    @app.get("/me")
    def me(user: CurrentUser) -> dict:
        return {"id": str(user.id), "role": user.role, "email": user.email,
                "display_name": user.display_name, "has_paypal": bool(user.paypal_payer_id)}

    @app.exception_handler(StaleState)
    @app.exception_handler(IllegalTransition)
    def _conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": f"job changed state, reload and retry ({exc})"}, 409)

    @app.exception_handler(MoneyError)
    def _money(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(ReviewError)
    @app.exception_handler(SuiteError)
    def _bad_suite(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, 422)

    app.include_router(jobs.router)
    app.include_router(submissions.router)
    app.include_router(webhooks.router)
    app.include_router(admin.router)
    app.include_router(receipts.router)
    app.include_router(auth.router)
    app.include_router(agents.router)
    app.include_router(demo.router)
    if app.state.services.settings.dev_auth:
        app.include_router(dev.router)
    return app


def default_services(cfg: Settings) -> Services:
    from verdict.db.session import make_session_factory
    from verdict.judge.llm import optional_client
    from verdict.paypal.client import PayPalClient
    from verdict.storage import make_store
    from verdict.worker.runners import make_runner

    def enqueue_grading(submission_id):  # imported lazily: the API must start without Redis
        from verdict.worker.tasks import grade_submission
        grade_submission.delay(str(submission_id))

    def kick_money(job_id):
        from verdict.worker.tasks import process_outbox
        process_outbox.delay()

    paypal = (PayPalClient(cfg.paypal_base_url, cfg.paypal_client_id, cfg.paypal_secret)
              if cfg.paypal_client_id and cfg.paypal_secret else None)
    Session = make_session_factory(cfg.database_url)  # noqa: N806
    svc = Services(settings=cfg, Session=Session, store=make_store(cfg, Session), paypal=paypal,
                   runner=make_runner(cfg), enqueue_grading=enqueue_grading,
                   llm=optional_client(cfg), kick_money=kick_money)
    if cfg.inline_worker:
        from verdict.worker.inline import start, start_money, start_ticker
        svc.enqueue_grading = lambda submission_id: start(svc, submission_id)
        svc.kick_money = lambda job_id: start_money(svc, job_id)
        start_ticker(svc)          # the beat schedule, in-process (no Celery, no Redis)
    return svc


def __getattr__(name: str):    # `uvicorn verdict.api.main:app` builds the app on first access
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
