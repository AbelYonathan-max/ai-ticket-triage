"""FastAPI application: the JSON API, the web pages and the health checks."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from triage import __version__
from triage.app_factory import build_service
from triage.db.migrate import current_revision, head_revision, upgrade
from triage.db.repository import Repository
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.domain.itil import SlaPolicy
from triage.domain.taxonomy import CATEGORIES, IMPACT_LABELS, TICKET_TYPES, URGENCY_LABELS, category_label
from triage.kb.retrieve import KnowledgeBase
from triage.security.auth import Principal, get_principal
from triage.security.web import RateLimiter, SecurityHeadersMiddleware
from triage.service import TriageService
from triage.settings import Settings, get_settings
from triage.telemetry import configure

log = logging.getLogger("triage.api")


@dataclass
class Runtime:
    settings: Settings
    service: TriageService
    engine: Engine
    sessions: sessionmaker[Session]
    limiter: RateLimiter
    login_limiter: RateLimiter
    templates: Jinja2Templates

    @property
    def kb(self) -> KnowledgeBase:
        return self.service.kb

    @property
    def policy(self) -> SlaPolicy:
        return self.service.policy


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def db_session(rt: Runtime = Depends(runtime)) -> Iterator[Session]:
    with session_scope(rt.sessions) as session:
        yield session


def repository(session: Session = Depends(db_session)) -> Repository:
    return Repository(session)


def principal(request: Request, rt: Runtime = Depends(runtime)) -> Principal:
    return get_principal(request, rt.settings)


def require_analyst(who: Principal = Depends(principal)) -> Principal:
    if not who.is_authenticated:
        raise HTTPException(status_code=401, detail="Sign in as an analyst to do this.")
    if not who.is_analyst:
        raise HTTPException(status_code=403, detail="Your account is not on the analyst list.")
    return who


def _templates() -> Jinja2Templates:
    from triage.api.views import due_in, london

    folder = Path(str(resources.files("triage.web").joinpath("templates")))
    templates = Jinja2Templates(directory=str(folder))
    env = templates.env
    env.filters["london"] = london
    env.filters["due_in"] = due_in
    env.filters["pct"] = lambda x: "n/a" if x is None else f"{100 * float(x):.0f}%"
    env.filters["category_label"] = category_label
    env.globals.update(
        CATEGORIES=CATEGORIES,
        TICKET_TYPES=TICKET_TYPES,
        IMPACT_LABELS=IMPACT_LABELS,
        URGENCY_LABELS=URGENCY_LABELS,
        APP_VERSION=__version__,
    )
    return templates


def create_app(
    settings: Settings | None = None,
    *,
    service: TriageService | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.check_web()
    configure(settings)
    service = service or build_service(settings)
    engine = engine or make_engine(settings)
    if settings.auto_migrate:
        upgrade(engine)
    sessions = make_session_factory(engine)
    if settings.seed_demo:
        from triage.jobs.seed import DEFAULT_PATH, seed_demo

        with session_scope(sessions) as session:
            if Repository(session).count_seed() == 0 and DEFAULT_PATH.exists():
                seed_demo(service, session)

    app = FastAPI(
        title="AI ticket triage",
        version=__version__,
        description=(
            "Triage IT service desk tickets: personal data redaction, ML classification, ITIL priority "
            "and SLA targets, safety rules and an optional Azure OpenAI assistant with guardrails."
        ),
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.runtime = Runtime(
        settings=settings,
        service=service,
        engine=engine,
        sessions=sessions,
        limiter=RateLimiter(settings.rate_limit_per_minute),
        login_limiter=RateLimiter(5),
        templates=_templates(),
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.env == "prod")
    static = Path(str(resources.files("triage.web").joinpath("static")))
    app.mount("/static", StaticFiles(directory=str(static)), name="static")

    from triage.api.routes_api import router as api_router
    from triage.api.routes_web import router as web_router

    app.include_router(api_router)
    app.include_router(web_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Liveness: the process is up and the model is loaded. Does not touch the database."""
        return {"status": "ok", "model": service.model.version}

    @app.get("/readyz", include_in_schema=False)
    def readyz(rt: Runtime = Depends(runtime)) -> JSONResponse:
        """Deep check used by the deploy smoke test: database reachable and schema up to date."""
        checks: dict[str, Any] = {"model": rt.service.model.version}
        try:
            with rt.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            current, head = current_revision(rt.engine), head_revision()
            checks["schema"] = current
            ok = current == head
            if not ok:
                checks["schema_expected"] = head
        except Exception as exc:  # report, do not crash
            log.warning("readyz_db_error", extra={"error": type(exc).__name__})
            checks["database"] = "unreachable"
            ok = False
        checks["status"] = "ok" if ok else "not ready"
        return JSONResponse(checks, status_code=200 if ok else 503)

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /tickets/\nDisallow: /api/\n")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        rt = runtime(request)
        who = get_principal(request, rt.settings)
        return rt.templates.TemplateResponse(
            request,
            "error.html",
            {"status": exc.status_code, "detail": exc.detail, "who": who, "settings": rt.settings},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> Response:
        log.exception("unhandled_error", extra={"path": request.url.path})
        return JSONResponse({"detail": "Something went wrong. The error has been logged."}, status_code=500)

    return app
