"""Server-rendered pages. They work without JavaScript and follow WCAG 2.2 AA patterns."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from triage.api.app import Runtime, principal, repository, require_analyst, runtime
from triage.api.views import ticket_out
from triage.db.repository import Repository, ReviewInput
from triage.domain.itil import priority_from
from triage.domain.taxonomy import CATEGORIES
from triage.privacy.redact import redact
from triage.security.auth import SESSION_COOKIE, SESSION_SECONDS, Principal, check_api_key, sign_session
from triage.security.web import CSRF_COOKIE, client_ip, csrf_token_for, csrf_valid, new_csrf_cookie

router = APIRouter(include_in_schema=False)
log = logging.getLogger("triage.web")


def render(
    request: Request,
    rt: Runtime,
    template: str,
    context: dict[str, Any],
    who: Principal,
    status_code: int = 200,
) -> Response:
    """Render a page, making sure the browser has a CSRF cookie for any form on it."""
    cookie = request.cookies.get(CSRF_COOKIE)
    new_cookie = None
    if not cookie:
        cookie = new_cookie = new_csrf_cookie()
    secret = rt.settings.session_secret.get_secret_value()
    context = {**context, "who": who, "settings": rt.settings, "csrf_token": csrf_token_for(secret, cookie)}
    response = rt.templates.TemplateResponse(request, template, context, status_code=status_code)
    if new_cookie:
        response.set_cookie(
            CSRF_COOKIE,
            new_cookie,
            httponly=True,
            samesite="strict",
            secure=rt.settings.env == "prod",
            path="/",
        )
    return response


def check_csrf(request: Request, rt: Runtime, token: str) -> None:
    secret = rt.settings.session_secret.get_secret_value()
    if not csrf_valid(secret, request.cookies.get(CSRF_COOKIE), token):
        raise HTTPException(
            status_code=400, detail="The form expired. Go back, refresh the page and try again."
        )


@router.get("/", response_class=HTMLResponse)
def index(request: Request, rt: Runtime = Depends(runtime), who: Principal = Depends(principal)) -> Response:
    return render(request, rt, "index.html", {"errors": {}, "form": {}}, who)


@router.post("/submit", response_class=HTMLResponse)
def submit(
    request: Request,
    subject: str = Form(""),
    body: str = Form(""),
    csrf_token: str = Form(""),
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> Response:
    check_csrf(request, rt, csrf_token)
    errors: dict[str, str] = {}
    if len(subject.strip()) < 3:
        errors["subject"] = "Enter a subject of at least 3 characters"
    elif len(subject) > 200:
        errors["subject"] = "Subject must be 200 characters or fewer"
    if len(body.strip()) < 3:
        errors["body"] = "Describe the problem or request"
    elif len(body) > rt.settings.max_body_chars:
        errors["body"] = f"Description must be {rt.settings.max_body_chars} characters or fewer"
    if errors:
        return render(
            request,
            rt,
            "index.html",
            {"errors": errors, "form": {"subject": subject, "body": body}},
            who,
            422,
        )
    if not who.is_analyst and not rt.limiter.allow(f"triage:{client_ip(request)}"):
        raise HTTPException(
            status_code=429, detail="Too many tickets from this address. Try again in a minute."
        )
    result = rt.service.triage(subject, body)
    ticket = repo.add_ticket(result, channel="portal")
    repo.audit(who.id or "anonymous", "ticket.submitted", ticket.id, channel="portal")
    log.info(
        "ticket_triaged",
        extra={
            "ticket_id": str(ticket.id),
            "category": result.category,
            "priority": result.priority,
            "needs_review": result.needs_review,
            "latency_ms": result.latency_ms,
        },
    )
    return RedirectResponse(f"/tickets/{ticket.id}?new=1", status_code=303)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_page(
    ticket_id: uuid.UUID,
    request: Request,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> Response:
    ticket = repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=404, detail="Ticket not found. It may have passed the retention period."
        )
    view = ticket_out(ticket, rt.kb, rt.policy)
    probabilities = ticket.result.explanation if ticket.result else {}
    return render(
        request,
        rt,
        "ticket.html",
        {
            "t": view,
            "is_new": request.query_params.get("new") == "1",
            "reviewed": request.query_params.get("reviewed") == "1",
            "explanation": probabilities,
            "policy": rt.policy,
        },
        who,
    )


@router.post("/tickets/{ticket_id}/review", response_class=HTMLResponse)
def review_form(
    ticket_id: uuid.UUID,
    request: Request,
    category: str = Form(...),
    ticket_type: str = Form(...),
    impact: int = Form(...),
    urgency: int = Form(...),
    notes: str = Form(""),
    csrf_token: str = Form(""),
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(require_analyst),
) -> Response:
    check_csrf(request, rt, csrf_token)
    if (
        category not in CATEGORIES
        or ticket_type not in ("incident", "request")
        or impact not in (1, 2, 3)
        or urgency not in (1, 2, 3)
    ):
        raise HTTPException(status_code=400, detail="Choose a valid category, type, impact and urgency.")
    ticket = repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    clean_notes = redact(notes[:1000]).text if notes.strip() else None
    review = repo.add_review(ticket, who.id, ReviewInput(category, ticket_type, impact, urgency, clean_notes))
    repo.audit(
        who.id, "ticket.reviewed", ticket.id, agreed=review.agreed, priority=priority_from(impact, urgency)
    )
    return RedirectResponse(f"/tickets/{ticket.id}?reviewed=1", status_code=303)


@router.get("/queue", response_class=HTMLResponse)
def queue(
    request: Request,
    view: str = "review",
    category: str | None = None,
    priority: int | None = None,
    page: int = 1,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> Response:
    page = max(1, page)
    category = category if category in CATEGORIES else None
    priority = priority if priority in (1, 2, 3, 4) else None
    needs_review = True if view == "review" else None
    status = "open" if view in ("review", "open") else None
    items, total = repo.list(
        seed_only=not who.is_analyst,
        needs_review=needs_review,
        category=category,
        priority=priority,
        status=status,
        limit=25,
        offset=(page - 1) * 25,
    )
    rows = [ticket_out(t, rt.kb, rt.policy) for t in items]
    return render(
        request,
        rt,
        "queue.html",
        {
            "rows": rows,
            "total": total,
            "view": view,
            "category": category,
            "priority": priority,
            "page": page,
            "pages": max(1, -(-total // 25)),
        },
        who,
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> Response:
    stats = repo.stats(seed_only=not who.is_analyst)
    return render(request, rt, "dashboard.html", {"stats": stats, "meta": rt.service.model.metadata}, who)


@router.get("/model", response_class=HTMLResponse)
def model_page(
    request: Request, rt: Runtime = Depends(runtime), who: Principal = Depends(principal)
) -> Response:
    return render(request, rt, "model.html", {"meta": rt.service.model.metadata}, who)


@router.get("/privacy", response_class=HTMLResponse)
def privacy(
    request: Request, rt: Runtime = Depends(runtime), who: Principal = Depends(principal)
) -> Response:
    return render(request, rt, "privacy.html", {}, who)


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request, rt: Runtime = Depends(runtime), who: Principal = Depends(principal)
) -> Response:
    mode = rt.settings.auth_mode
    if mode == "easyauth":
        return RedirectResponse("/.auth/login/aad?post_login_redirect_uri=/queue", status_code=302)
    if mode == "none" or who.is_analyst:
        return RedirectResponse("/queue", status_code=302)
    return render(request, rt, "login.html", {"error": None}, who)


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    key: str = Form(""),
    csrf_token: str = Form(""),
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> Response:
    if rt.settings.auth_mode != "apikey":
        raise HTTPException(status_code=404, detail="Not found")
    check_csrf(request, rt, csrf_token)
    if not rt.login_limiter.allow(f"login:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait a minute and try again.")
    if not check_api_key(rt.settings, key):
        repo.audit("anonymous", "analyst.login_failed")
        return render(request, rt, "login.html", {"error": "That key is not right."}, who, 401)
    repo.audit("analyst", "analyst.login")
    response = RedirectResponse("/queue", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(rt.settings.session_secret.get_secret_value(), "analyst"),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=rt.settings.env == "prod",
        path="/",
    )
    return response


@router.post("/logout", response_class=HTMLResponse)
def logout(request: Request, csrf_token: str = Form(""), rt: Runtime = Depends(runtime)) -> Response:
    check_csrf(request, rt, csrf_token)
    if rt.settings.auth_mode == "easyauth":
        return RedirectResponse("/.auth/logout?post_logout_redirect_uri=/", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
