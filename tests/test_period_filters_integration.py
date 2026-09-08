from datetime import date

import pytest
from fastapi import status

pytestmark = [pytest.mark.integration, pytest.mark.redis]

PERIODS = ["1w", "1m", "3m", "1y"]


def create_and_click(integration_client, url: str, times: int) -> dict:
    response = integration_client.post("/shorten", json={"long_url": url})
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    for _ in range(times):
        response = integration_client.get(f"/{data['short_code']}", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
    return data


@pytest.mark.parametrize("period", PERIODS)
def test_analytics_periods_include_todays_clicks(integration_client, period):
    data = create_and_click(integration_client, "https://example.com", 3)

    response = integration_client.get(
        f"/urls/{data['short_code']}/analytics", params={"period": period}
    )
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["clicks_per_day"] == [{"date": str(date.today()), "count": 3}]


@pytest.mark.parametrize("period", PERIODS)
def test_history_periods_include_todays_clicks(integration_client, period):
    data = create_and_click(integration_client, "https://example.com", 2)

    response = integration_client.get(
        f"/urls/{data['short_code']}/history", params={"period": period}
    )
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2


@pytest.mark.parametrize("period", PERIODS)
def test_top_urls_periods_include_todays_clicks(integration_client, period):
    most_clicked = create_and_click(integration_client, "https://example.com/most", 4)
    create_and_click(integration_client, "https://example.com/least", 2)

    response = integration_client.get("/urls/top", params={"period": period})
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["count"] == 2
    assert body["items"][0]["short_code"] == most_clicked["short_code"]
    assert body["items"][0]["click_count"] == 4
    assert body["items"][1]["click_count"] == 2


def test_analytics_invalid_period_treated_as_no_filter(integration_client):
    data = create_and_click(integration_client, "https://example.com", 3)

    response = integration_client.get(
        f"/urls/{data['short_code']}/analytics", params={"period": "bogus"}
    )
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["clicks_per_day"] == [{"date": str(date.today()), "count": 3}]


def test_history_invalid_period_treated_as_no_filter(integration_client):
    data = create_and_click(integration_client, "https://example.com", 2)

    response = integration_client.get(
        f"/urls/{data['short_code']}/history", params={"period": "bogus"}
    )
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2


def test_top_urls_invalid_period_returns_unsynced_db_click_counts(integration_client):
    # since_calculation("bogus") returns None, so get_top_urls takes its
    # no-period branch, which reads URL.click_count from Postgres. Live clicks
    # only update the Redis hash; the DB column stays 0 until the scheduler
    # syncs, so a URL clicked 4 times shows up with click_count == 0.
    data = create_and_click(integration_client, "https://example.com", 4)

    response = integration_client.get("/urls/top", params={"period": "bogus"})
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["short_code"] == data["short_code"]
    assert body["items"][0]["click_count"] == 0
