"""Who is making the request, and are they an analyst?

Three modes:
- easyauth: Azure Container Apps authentication (Microsoft Entra ID) signs people in and passes the
  signed-in user to the app in X-MS-CLIENT-PRINCIPAL headers. The platform strips those headers
  from incoming requests, so they are only trusted when TRIAGE_TRUST_EASY_AUTH_HEADERS is set.
  Analysts are the Entra object IDs listed in TRIAGE_ANALYST_IDS.
- apikey: for subscriptions where an Entra app registration cannot be created. Analysts sign in
  with a shared key from Key Vault and get a short-lived signed session cookie.
- none: local development only; everyone is an analyst. Refused when TRIAGE_ENV=prod.

Anonymous visitors can always submit tickets and see their own result by its unguessable ID.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from starlette.requests import Request

from triage.settings import Settings

SESSION_COOKIE = "triage_session"
SESSION_SECONDS = 8 * 3600


@dataclass(frozen=True)
class Principal:
    id: str  # Entra object ID, "analyst" for the shared key, "dev" locally, "" when anonymous
    name: str
    is_analyst: bool
    method: str  # easyauth, apikey, none, anonymous

    @property
    def is_authenticated(self) -> bool:
        return self.method != "anonymous"


ANONYMOUS = Principal(id="", name="", is_analyst=False, method="anonymous")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_session(secret: str, subject: str, now: float | None = None) -> str:
    payload = _b64(json.dumps({"sub": subject, "exp": int((now or time.time()) + SESSION_SECONDS)}).encode())
    mac = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{mac}"


def verify_session(secret: str, token: str, now: float | None = None) -> str | None:
    payload, _, mac = token.partition(".")
    if not payload or not mac:
        return None
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("exp", 0)) < (now or time.time()):
        return None
    return str(data.get("sub", "")) or None


def check_api_key(settings: Settings, supplied: str | None) -> bool:
    key = settings.analyst_api_key.get_secret_value() if settings.analyst_api_key else ""
    return bool(key) and bool(supplied) and hmac.compare_digest(key.encode(), (supplied or "").encode())


def _easy_auth_principal(request: Request, settings: Settings) -> Principal:
    oid = request.headers.get("x-ms-client-principal-id", "").strip().lower()
    name = request.headers.get("x-ms-client-principal-name", "").strip()
    if not oid:
        encoded = request.headers.get("x-ms-client-principal")
        if encoded:
            try:
                claims = json.loads(base64.b64decode(encoded)).get("claims", [])
            except (ValueError, json.JSONDecodeError):
                claims = []
            values = {c.get("typ"): c.get("val") for c in claims if isinstance(c, dict)}
            oid = str(
                values.get("http://schemas.microsoft.com/identity/claims/objectidentifier")
                or values.get("oid")
                or ""
            ).lower()
            name = name or str(values.get("preferred_username") or values.get("name") or "")
    if not oid:
        return ANONYMOUS
    return Principal(
        id=oid, name=name or "Signed in", is_analyst=oid in settings.analyst_id_set, method="easyauth"
    )


def get_principal(request: Request, settings: Settings) -> Principal:
    if settings.auth_mode == "none":
        return Principal(id="dev", name="Local developer", is_analyst=True, method="none")
    if settings.auth_mode == "easyauth":
        if not settings.trust_easy_auth_headers:
            return ANONYMOUS
        return _easy_auth_principal(request, settings)
    # apikey mode: an X-API-Key header (for scripts) or a signed session cookie (for the browser).
    if check_api_key(settings, request.headers.get("x-api-key")):
        return Principal(id="analyst", name="Analyst (API key)", is_analyst=True, method="apikey")
    token = request.cookies.get(SESSION_COOKIE)
    if token and verify_session(settings.session_secret.get_secret_value(), token) == "analyst":
        return Principal(id="analyst", name="Analyst", is_analyst=True, method="apikey")
    return ANONYMOUS
