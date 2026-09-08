import pytest
from fastapi import status

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def create_short_url(integration_client, long_url: str) -> dict:
    response = integration_client.post("/shorten", json={"long_url": long_url})
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def click_with_referer(integration_client, short_code: str, referer: str, times: int = 1) -> None:
    for _ in range(times):
        response = integration_client.get(
            f"/{short_code}",
            headers={"Referer": referer},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_302_FOUND


def test_top_referrers_multiple_domains_and_counts(integration_client):
    data = create_short_url(integration_client, "https://example.com/referrer-target")

    click_with_referer(integration_client, data["short_code"], "https://twitter.com/some-post", times=2)
    click_with_referer(integration_client, data["short_code"], "https://github.com/user/repo", times=1)

    response = integration_client.get(f"/urls/{data['short_code']}/stats")
    assert response.status_code == status.HTTP_200_OK

    top_referrers = response.json()["top_referrers"]
    assert {"domain": "twitter.com", "click_count": 2} in top_referrers
    assert {"domain": "github.com", "click_count": 1} in top_referrers


def test_top_referrers_strips_subdomain(integration_client):
    data = create_short_url(integration_client, "https://example.com/referrer-target")

    click_with_referer(integration_client, data["short_code"], "https://blog.twitter.com/some-post", times=1)

    response = integration_client.get(f"/urls/{data['short_code']}/stats")
    assert response.status_code == status.HTTP_200_OK

    top_referrers = response.json()["top_referrers"]
    assert top_referrers == [{"domain": "twitter.com", "click_count": 1}]
