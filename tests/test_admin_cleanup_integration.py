import pytest
from fastapi import status

from datetime import datetime, timezone, timedelta

pytestmark = [pytest.mark.integration, pytest.mark.redis]
ADMIN_HEADERS = {"X-API-Key": "test-key"}


def create_short_url(integration_client, long_url: str, expires_at: str | None = None) -> dict:
    payload = {"long_url": long_url}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    response = integration_client.post("/shorten", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def test_cleanup_deactivates_only_expired_urls(integration_client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    expired = create_short_url(integration_client, "https://example.com/expired-page", expires_at=past)
    active = create_short_url(integration_client, "https://example.com/active-page")

    response = integration_client.post("/admin/urls/cleanup", headers=ADMIN_HEADERS)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["deleted_count"] == 1
    assert body["detail"] == "Cleaned up 1 expired URLs"

    response = integration_client.get(f"/{expired['short_code']}", follow_redirects=False)
    assert response.status_code == status.HTTP_410_GONE

    response = integration_client.get(f"/{active['short_code']}", follow_redirects=False)
    assert response.status_code == status.HTTP_302_FOUND
    assert response.headers["location"] == active["long_url"]


def test_cleanup_with_nothing_expired_deletes_zero(integration_client):
    create_short_url(integration_client, "https://example.com/active-page")

    response = integration_client.post("/admin/urls/cleanup", headers=ADMIN_HEADERS)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["deleted_count"] == 0
    assert body["detail"] == "Cleaned up 0 expired URLs"
