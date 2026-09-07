import pytest
from fastapi import status

from datetime import datetime, timezone, timedelta

pytestmark = [pytest.mark.integration, pytest.mark.redis]
ADMIN_HEADERS = {"X-API-Key": "test-key"}

def create_short_url(integration_client) -> dict:
    response = integration_client.post("/shorten", json={"long_url": "https://example.com/some-page"})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()

def follow_redirect(integration_client, data: dict, times: int = 1, expected_url: str | None = None) -> None:
    for _ in range(times):
        response = integration_client.get(f"/{data['short_code']}", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == expected_url if expected_url else data["long_url"]

def delete_url(integration_client, data):
    response = integration_client.delete(f"/admin/urls/{data['short_code']}", headers=ADMIN_HEADERS)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL deleted successfully"

def test_create_then_redirect(integration_client):
    data = create_short_url(integration_client=integration_client)
    follow_redirect(integration_client, data)

def test_redirect_increments_click_count(integration_client):
    data = create_short_url(integration_client=integration_client)
    follow_redirect(integration_client, data, times=2) 

    response = integration_client.get(f"/urls/{data['short_code']}/stats")
    assert response.json()["click_count"] == 2

def test_update_with_valid_edit_token(integration_client):
    data = create_short_url(integration_client)

    response = integration_client.patch(f"/urls/{data['short_code']}", json={"new_url": "https://new.com", "edit_token": data["edit_token"]})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL updated"

    follow_redirect(integration_client, data, expected_url="https://new.com/")

def test_update_with_wrong_token(integration_client):
    data = create_short_url(integration_client)

    response = integration_client.patch(f"/urls/{data['short_code']}", json={"new_url": "https://new.com", "edit_token": "wrong_token"})
    assert response.status_code == status.HTTP_404_NOT_FOUND

def test_delete_then_redirect_gone(integration_client):
    data = create_short_url(integration_client)

    delete_url(integration_client, data)

    response = integration_client.get(f"/{data['short_code']}", follow_redirects=False)
    assert response.status_code == status.HTTP_410_GONE

def test_restore_deleted_url(integration_client):
    data = create_short_url(integration_client)

    delete_url(integration_client, data)

    response = integration_client.post(f"/admin/urls/{data['short_code']}/restore", headers=ADMIN_HEADERS)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["detail"] == "URL restored successfully"

    follow_redirect(integration_client, data)

def test_expired_url_returns_410(integration_client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    response = integration_client.post(
        "/shorten",
        json={"long_url": "https://example.com/expired-page", "expires_at": past},
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    response = integration_client.get(f"/{data['short_code']}", follow_redirects=False)
    assert response.status_code == status.HTTP_410_GONE
    assert response.json()["detail"] == "URL has expired."

def test_unknown_code_404(integration_client):
    response = integration_client.get("/neverexisted", follow_redirects=False)
    assert response.status_code == status.HTTP_404_NOT_FOUND

