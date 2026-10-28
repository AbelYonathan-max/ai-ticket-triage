from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from triage.security.web import CSRF_COOKIE


def csrf(client: TestClient, path: str = "/") -> str:
    page = client.get(path)
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page.text)
    assert match, "no CSRF token on the page"
    return match.group(1)


def submit(client: TestClient, subject: str, body: str) -> Any:
    token = csrf(client)
    return client.post(
        "/submit", data={"subject": subject, "body": body, "csrf_token": token}, follow_redirects=False
    )


def test_home_page_renders_accessible_form(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert '<label for="subject">' in page.text and '<label for="body">' in page.text
    assert 'href="#main"' in page.text  # skip link
    assert CSRF_COOKIE in page.cookies


def test_submit_redirects_to_result_page(client: TestClient) -> None:
    response = submit(client, "Can't print", "The printer on the 3rd floor is offline. Thanks, Sam Smith")
    assert response.status_code == 303
    location = response.headers["location"]
    page = client.get(location)
    assert page.status_code == 200
    assert "Ticket triaged" in page.text
    assert "Sam Smith" not in page.text and "[NAME]" in page.text
    assert 'name="robots" content="noindex' in page.text


def test_submit_without_csrf_token_is_rejected(client: TestClient) -> None:
    client.get("/")
    response = client.post(
        "/submit", data={"subject": "Hello", "body": "World wide"}, headers={"accept": "text/html"}
    )
    assert response.status_code == 400
    assert "form expired" in response.text


def test_validation_errors_are_shown_with_summary(client: TestClient) -> None:
    response = submit(client, "", "")
    assert response.status_code == 422
    assert "There is a problem" in response.text
    assert 'href="#subject"' in response.text and 'href="#body"' in response.text


def test_queue_dashboard_model_privacy_pages(client: TestClient) -> None:
    submit(client, "VPN", "The VPN drops all the time when I work from home")
    for path in ["/queue?view=all", "/queue?view=review", "/dashboard", "/model", "/privacy"]:
        page = client.get(path)
        assert page.status_code == 200, path
        assert "<h1>" in page.text
    assert "VPN" in client.get("/queue?view=all").text


def test_review_form_for_analysts(client: TestClient) -> None:
    location = submit(client, "Teams", "Teams keeps crashing when I share my screen").headers["location"]
    page = client.get(location)
    assert "Review this triage" in page.text  # auth_mode none makes everyone an analyst locally
    token = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page.text).group(1)  # type: ignore[union-attr]
    ticket_id = location.split("/")[2].split("?")[0]
    response = client.post(
        f"/tickets/{ticket_id}/review",
        data={
            "category": "m365",
            "ticket_type": "incident",
            "impact": "3",
            "urgency": "1",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Review saved" in client.get(response.headers["location"]).text


def test_anonymous_visitors_cannot_review(make_client: Any) -> None:
    client = make_client(auth_mode="apikey", analyst_api_key="k" * 32)
    location = submit(client, "Teams", "Teams keeps crashing when I share my screen").headers["location"]
    page = client.get(location)
    assert "Review this triage" not in page.text
    ticket_id = location.split("/")[2].split("?")[0]
    token = csrf(client)
    response = client.post(
        f"/tickets/{ticket_id}/review",
        data={
            "category": "m365",
            "ticket_type": "incident",
            "impact": "3",
            "urgency": "1",
            "csrf_token": token,
        },
        headers={"accept": "text/html"},
    )
    assert response.status_code == 401


def test_api_key_login_flow(make_client: Any) -> None:
    client = make_client(auth_mode="apikey", analyst_api_key="k" * 32)
    token = csrf(client, "/login")
    bad = client.post("/login", data={"key": "nope", "csrf_token": token})
    assert bad.status_code == 401 and "not right" in bad.text
    good = client.post("/login", data={"key": "k" * 32, "csrf_token": token}, follow_redirects=False)
    assert good.status_code == 303 and "triage_session" in good.cookies
    assert "(analyst)" in client.get("/queue").text
    token = csrf(client, "/queue")
    client.post("/logout", data={"csrf_token": token})
    assert "Analyst sign in" in client.get("/").text


def test_easyauth_login_redirects_to_platform(make_client: Any) -> None:
    client = make_client(auth_mode="easyauth", trust_easy_auth_headers=True)
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/.auth/login/aad")


def test_unknown_page_is_a_friendly_404(client: TestClient) -> None:
    page = client.get("/tickets/00000000-0000-0000-0000-000000000000", headers={"accept": "text/html"})
    assert page.status_code == 404 and "Page not found" in page.text


def test_robots_txt(client: TestClient) -> None:
    assert "Disallow: /tickets/" in client.get("/robots.txt").text
