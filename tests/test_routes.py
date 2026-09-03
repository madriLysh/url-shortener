import pytest
from api.dependencies import get_url_service
from main import build_application
from fastapi.testclient import TestClient
from services import URLService
from fastapi import status
from config import Config
from models import URL
from datetime import datetime, timezone, timedelta


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
    assert "edit_token" in response.json()
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

def test_update_url_valid_token_returns_200_and_updates(client: TestClient, service: URLService, db_session):
    code, token = service.create_url("https://old.com", creator_ip="1.2.3.4")

    response = client.patch(f"/urls/{code}", json={"new_url": "https://new.com", "edit_token": token})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL updated"

    row = db_session.query(URL).filter(URL.edit_token == token).first()
    assert row.long_url == "https://new.com/"

def test_update_url_invalid_token_returns_404(client: TestClient, service: URLService, db_session):
    code, token = service.create_url("https://old.com", creator_ip="1.2.3.4")

    response = client.patch(f"/urls/{code}", json={"new_url": "https://new.com", "edit_token": "wrong_token"})
    assert response.status_code == status.HTTP_404_NOT_FOUND

def test_update_url_malformed_url_returns_422(client: TestClient):
    response = client.patch("/urls/anything", json={"new_url": "not-a-url", "edit_token": "x"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

def test_update_url_unknown_code_returns_404(client: TestClient):
    response = client.patch("/urls/ghost1", json={"new_url": "https://example.com", "edit_token": "tok"},)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]

def test_admin_route_without_configured_key_returns_403(client: TestClient):
    response = client.delete("/admin/urls/anycode", headers={"X-API-KEY": "test_key"})
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Admin API key not configured." == response.json()["detail"]

def test_admin_route_missing_header_returns_401(client: TestClient, monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    response = client.delete("/admin/urls/anycode")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "X-API-Key header missing." == response.json()["detail"]

def test_admin_route_wrong_key_returns_403(client: TestClient, monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    response = client.delete("/admin/urls/anycode", headers={"X-API-KEY": "wrong_key"})
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Invalid API key." == response.json()["detail"] 

def test_admin_delete_valid_key_deactivates_url(client: TestClient, db_session, monkeypatch):
    db_session.add(URL(
        short_code="delme1", 
        long_url="https://example.com", 
        edit_token="tok", 
        is_active=True
    ))
    db_session.commit()

    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    response = client.delete("/admin/urls/delme1", headers={"X-API-KEY": "test_key"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL deleted successfully"

    row = db_session.query(URL).filter(URL.short_code == "delme1").first()
    assert row.is_active is False

def test_admin_restore_valid_key_restores_url(client: TestClient, db_session, monkeypatch):
    db_session.add(URL(
        short_code="resto1", 
        long_url="https://example.com", 
        edit_token="tok", 
        is_active=False
    ))
    db_session.commit()

    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    response = client.post("/admin/urls/resto1/restore", headers={"X-API-Key": "test_key"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL restored successfully"

    row = db_session.query(URL).filter(URL.short_code == "resto1").first()
    assert row.is_active is True

def test_admin_cleanup_returns_deleted_count(client: TestClient, db_session, monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    db_session.add(URL(
        short_code="old123", 
        long_url="https://example.com",  
        is_active=True,
        expires_at =datetime.now(timezone.utc) - timedelta(hours=1),
        edit_token ="tok1"
    ))

    db_session.add(URL(
        short_code="fresh1", 
        long_url="https://example.com",  
        is_active=True,
        expires_at = datetime.now(timezone.utc) + timedelta(days=1),
        edit_token ="tok2"
    ))
    db_session.commit()

    response = client.post("/admin/urls/cleanup", headers={"X-API-Key": "test_key"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["deleted_count"] == 1
    assert response.json()["detail"] == "Cleaned up 1 expired URLs"

    row = db_session.query(URL).filter(URL.short_code == "old123").first()
    assert row.is_active is False

    row = db_session.query(URL).filter(URL.short_code == "fresh1").first()
    assert row.is_active is True

def test_admin_delete_unknown_code_returns_404(client: TestClient, monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test_key")

    response = client.delete("/admin/urls/nope99", headers={"X-API-Key": "test_key"})
    assert response.status_code == status.HTTP_404_NOT_FOUND