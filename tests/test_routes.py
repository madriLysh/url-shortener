import pytest
from api.dependencies import get_url_service
from main import build_application
from fastapi.testclient import TestClient
from services import URLService
from fastapi import status
from config import Config
from models import URL
from datetime import datetime, timezone

@pytest.fixture
def client(service):
    app = build_application()
    app.dependency_overrides[get_url_service] = lambda : service

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

def test_create_short_url_returns_201_and_stores_url(client: TestClient, db_session):
    response = client.post("/shorten", json={"long_url": "https://example.com"})
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()

    row = db_session.query(URL).filter(URL.short_code == data["short_code"]).first()
    assert row is not None
    assert row.long_url == data["long_url"]

    assert data["short_url"] == f"{Config.BASE_URL}/{data['short_code']}"

def test_create_short_url_rejects_private_url_returns_400(client: TestClient):
    response = client.post("/shorten", json={"long_url": "http://127.0.0.1/admin"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST

def test_create_short_url_malformed_url_returns_422(client: TestClient):
    response = client.post("/shorten", json={"long_url": "not-a-url"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

def test_create_short_url_taken_custom_code_returns_400(client: TestClient):
    response = client.post("/shorten", json={"long_url": "https://example.com", "custom_alias": "taken1"})
    assert response.status_code == status.HTTP_201_CREATED

    response = client.post("/shorten", json={"long_url": "https://example.com", "custom_alias": "taken1"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "already in use" in response.json()["detail"]

def test_redirect_hit_returns_302_with_location(client: TestClient, service: URLService, db_session):
    service.create_url("https://example.com", creator_ip="1.2.3.4")
    row = db_session.query(URL).filter(URL.long_url == "https://example.com").first()

    response = client.get(f"/{row.short_code}", follow_redirects=False)
    assert response.status_code == status.HTTP_302_FOUND
    assert response.headers["location"] == row.long_url

def test_redirect_unknown_code_returns_404(client: TestClient, service: URLService):
    response = client.get("/nothing", follow_redirects=False)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "URL not found."

def test_redirect_expired_url_returns_410(client: TestClient, service: URLService, db_session):
    db_session.add(URL(
        short_code="url1",
        long_url="https://example.com",
        is_active=True,
        expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc)
    ))
    db_session.commit()

    response = client.get(f"/url1", follow_redirects=False)
    assert response.status_code == status.HTTP_410_GONE
 