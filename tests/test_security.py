from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from triage.security.auth import sign_session, verify_session
from triage.security.web import RateLimiter, client_ip, csrf_token_for, csrf_valid
from triage.settings import Settings


def test_session_tokens_are_signed_and_expire() -> None:
    token = sign_session("secret", "analyst", now=1000)
    assert verify_session("secret", token, now=1001) == "analyst"
    assert verify_session("other-secret", token, now=1001) is None
    assert verify_session("secret", token, now=1000 + 9 * 3600) is None
    payload, mac = token.split(".")
    assert verify_session("secret", payload + "x." + mac, now=1001) is None
    assert verify_session("secret", "garbage", now=1001) is None


def test_csrf_tokens_are_bound_to_the_cookie() -> None:
    token = csrf_token_for("secret", "cookie-a")
    assert csrf_valid("secret", "cookie-a", token)
    assert not csrf_valid("secret", "cookie-b", token)
    assert not csrf_valid("secret", None, token)
    assert not csrf_valid("secret", "cookie-a", "")


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 61
    assert limiter.allow("a")


def request_with(headers: dict[str, str], host: str = "10.0.0.1") -> Any:
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


def test_client_ip_uses_the_address_added_by_the_ingress() -> None:
    assert client_ip(request_with({"x-forwarded-for": "1.1.1.1, 203.0.113.9"})) == "203.0.113.9"
    assert client_ip(request_with({})) == "10.0.0.1"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"auth_mode": "none"}, "only allowed outside prod"),
        ({"auth_mode": "easyauth"}, "TRUST_EASY_AUTH_HEADERS"),
        ({"auth_mode": "apikey"}, "TRIAGE_ANALYST_API_KEY"),
        ({"auth_mode": "apikey", "analyst_api_key": "x" * 32, "sql_server": None}, "TRIAGE_SQL_SERVER"),
    ],
)
def test_prod_settings_refuse_unsafe_configuration(overrides: dict[str, Any], message: str) -> None:
    base: dict[str, Any] = {"env": "prod", "sql_server": "x.database.windows.net", "sql_database": "triage"}
    base.update(overrides)
    with pytest.raises(ValueError, match=message):
        Settings(**base).check_web()


def test_jobs_do_not_need_sign_in_settings() -> None:
    settings = Settings(env="prod", sql_server="x.database.windows.net", sql_database="triage")
    assert settings.auth_mode == "none"  # fine for a job, refused when serving requests
    with pytest.raises(ValueError, match="only allowed outside prod"):
        settings.check_web()


def test_settings_parse_analyst_ids_and_llm_requirements() -> None:
    s = Settings(analyst_ids=" AAA , bbb ,,")
    assert s.analyst_id_set == frozenset({"aaa", "bbb"})
    with pytest.raises(ValueError, match="TRIAGE_OPENAI_ENDPOINT"):
        Settings(llm_provider="azure_openai")
