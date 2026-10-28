from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from fastapi.testclient import TestClient

TICKET = {
    "subject": "VPN dropping",
    "body": "The VPN keeps dropping when I work from home. Call me on 07700 900123.",
}


def post_ticket(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/api/v1/triage", json={**TICKET, **overrides})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_triage_returns_a_full_decision(client: TestClient) -> None:
    body = post_ticket(client)
    assert body["category"] == "network"
    assert body["priority"] in {"P1", "P2", "P3", "P4"}
    assert body["personal_data_removed"] == {"PHONE": 1}
    assert "07700" not in body["redacted_body"]
    assert body["knowledge_base"][0]["id"] == "KB004"
    assert body["assist"]["status"] == "ok"
    assert body["url"].endswith(f"/tickets/{body['id']}")


def test_get_ticket_round_trip_and_404(client: TestClient) -> None:
    created = post_ticket(client)
    fetched = client.get(f"/api/v1/tickets/{created['id']}").json()
    assert fetched["id"] == created["id"] and fetched["priority"] == created["priority"]
    assert client.get(f"/api/v1/tickets/{uuid.uuid4()}").status_code == 404


def test_validation_errors(client: TestClient) -> None:
    assert client.post("/api/v1/triage", json={"subject": "x", "body": "ok ok"}).status_code == 422
    assert client.post("/api/v1/triage", json={"subject": "Hello", "body": "y" * 6001}).status_code == 422
    assert client.post("/api/v1/triage", json={"subject": "   ", "body": "valid body"}).status_code == 422
    # A form-encoded body is not accepted as JSON (protects against cross-site form posts).
    assert client.post("/api/v1/triage", data=TICKET).status_code == 422


def test_review_updates_status_and_records_agreement(client: TestClient) -> None:
    created = post_ticket(client)
    review = {
        "category": created["category"],
        "ticket_type": created["ticket_type"],
        "impact": created["impact"],
        "urgency": created["urgency"],
        "notes": "Checked with Jo Bloggs on 07700 900456",
    }
    response = client.post(f"/api/v1/tickets/{created['id']}/review", json=review)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "reviewed"
    assert data["reviews"][0]["agreed"] is True
    assert "07700" not in data["reviews"][0]["notes"]


def test_list_requires_analyst_and_filters(make_client: Any) -> None:
    client = make_client(auth_mode="easyauth", trust_easy_auth_headers=True, analyst_ids="aaaa-1111")
    post_ticket(client)
    assert client.get("/api/v1/tickets").status_code == 401
    other = {"x-ms-client-principal-id": "bbbb-2222", "x-ms-client-principal-name": "someone@example.org"}
    assert client.get("/api/v1/tickets", headers=other).status_code == 403
    analyst = {"x-ms-client-principal-id": "AAAA-1111", "x-ms-client-principal-name": "analyst@example.org"}
    page = client.get("/api/v1/tickets?limit=5", headers=analyst).json()
    assert page["total"] >= 1 and len(page["items"]) <= 5
    assert client.get("/api/v1/tickets?priority=9", headers=analyst).status_code == 422


def test_easy_auth_headers_ignored_unless_trusted(make_client: Any) -> None:
    client = make_client(auth_mode="easyauth", trust_easy_auth_headers=False, analyst_ids="aaaa-1111")
    headers = {"x-ms-client-principal-id": "aaaa-1111"}
    assert client.get("/api/v1/tickets", headers=headers).status_code == 401


def test_easy_auth_principal_blob_is_parsed(make_client: Any) -> None:
    client = make_client(auth_mode="easyauth", trust_easy_auth_headers=True, analyst_ids="cccc-3333")
    blob = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": "cccc-3333"},
            {"typ": "preferred_username", "val": "analyst@example.org"},
        ],
    }
    headers = {"x-ms-client-principal": base64.b64encode(json.dumps(blob).encode()).decode()}
    assert client.get("/api/v1/tickets", headers=headers).status_code == 200


def test_api_key_mode(make_client: Any) -> None:
    client = make_client(auth_mode="apikey", analyst_api_key="k" * 32)
    assert client.get("/api/v1/tickets").status_code == 401
    assert client.get("/api/v1/tickets", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/api/v1/tickets", headers={"x-api-key": "k" * 32}).status_code == 200


def test_rate_limit_applies_to_anonymous_callers(make_client: Any) -> None:
    client = make_client(auth_mode="apikey", analyst_api_key="k" * 32, rate_limit_per_minute=2)
    post_ticket(client)
    post_ticket(client)
    assert client.post("/api/v1/triage", json=TICKET).status_code == 429
    # Analysts are not limited.
    response = client.post("/api/v1/triage", json=TICKET, headers={"x-api-key": "k" * 32})
    assert response.status_code == 201


def test_stats_and_model_endpoints(client: TestClient) -> None:
    post_ticket(client)
    stats = client.get("/api/v1/stats").json()
    assert stats["total"] >= 1 and stats["by_category"]["network"] >= 1
    model = client.get("/api/v1/model").json()
    assert model["version"] == "test+tiny" and model["review_threshold"] == 0.6


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["schema"] == "0001"


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]


def test_openapi_lists_the_api_only(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/triage" in paths and "/submit" not in paths
