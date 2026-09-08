import pytest
from fastapi import status

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def test_create_with_custom_alias_and_redirect(integration_client):
    response = integration_client.post(
        "/shorten",
        json={"long_url": "https://example.com/aliased-page", "custom_alias": "myalias"},
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["short_code"] == "myalias"

    response = integration_client.get("/myalias", follow_redirects=False)
    assert response.status_code == status.HTTP_302_FOUND
    assert response.headers["location"] == data["long_url"]


def test_duplicate_custom_alias_rejected(integration_client):
    response = integration_client.post(
        "/shorten",
        json={"long_url": "https://example.com/first", "custom_alias": "takenalias"},
    )
    assert response.status_code == status.HTTP_201_CREATED

    response = integration_client.post(
        "/shorten",
        json={"long_url": "https://example.com/second", "custom_alias": "takenalias"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Custom code 'takenalias' already in use."


def test_invalid_custom_alias_rejected(integration_client):
    response = integration_client.post(
        "/shorten",
        json={"long_url": "https://example.com/invalid-alias", "custom_alias": "ab!"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
