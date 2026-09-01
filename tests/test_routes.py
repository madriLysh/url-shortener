import pytest
from api.dependencies import get_url_service
from main import build_application
from fastapi.testclient import TestClient
from services import URLService
from fastapi import status
from config import Config
@pytest.fixture
def client(service):
    app = build_application()
    app.dependency_overrides[get_url_service] = lambda : service

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

def test_create_short_url_returns_201_and_stores_url(client: TestClient, service: URLService):
    response = client.post("/shorten", json={"long_url": "https://example.com"})
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["long_url"] == "https://example.com/"
    assert data["short_url"] == f"{Config.BASE_URL}/{data["short_code"]}"