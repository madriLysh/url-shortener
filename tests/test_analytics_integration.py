import pytest
from fastapi import status
from datetime import date

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def create_and_click(integration_client, url: str, times: int) -> dict:
    response = integration_client.post("/shorten", json={"long_url": url})
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    for _ in range(times):
        response = integration_client.get(f"/{data['short_code']}", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
    return data


def test_stats_shape_and_source(integration_client):
    data = create_and_click(integration_client, "https://example.com", 1)

    response = integration_client.get(f"/urls/{data['short_code']}/stats")
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["click_count"] == 1
    assert body["source"] == "hybrid"
    assert body["unique_visitors"] == 1
    assert body["top_referrers"] == []


def test_analytics_clicks_per_day(integration_client):
    data = create_and_click(integration_client, "https://example.com", 3)

    response = integration_client.get(f"/urls/{data['short_code']}/analytics?period=1d")
    assert response.status_code == status.HTTP_200_OK

    days = response.json()["clicks_per_day"]
    assert len(days) == 1
    assert days[0]["count"] == 3
    assert days[0]["date"] == str(date.today())


def test_analytics_empty_period(integration_client):
    data = create_and_click(integration_client, "https://example.com", 0)

    response = integration_client.get(f"/urls/{data['short_code']}/analytics?period=1d")
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["clicks_per_day"] == []
    assert body["top_countries"] == []
    assert body["top_browsers"] == []


def test_history_returns_clicks(integration_client):
    response = integration_client.post("/shorten", json={"long_url": "https://example.com"})
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    agents = ["agent-a", "agent-b"]
    for agent in agents:
        response = integration_client.get(
            f"/{data['short_code']}",
            headers={"User-Agent": agent},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_302_FOUND

    response = integration_client.get(f"/urls/{data['short_code']}/history")
    assert response.status_code == status.HTTP_200_OK

    items = response.json()["items"]
    assert len(items) == 2
    assert {click["user_agent"] for click in items} == set(agents)


def test_recent_urls_ordering(integration_client):
    urls = ["https://example.com", "https://new.com", "https://old.com"]
    short_codes = []
    for url in urls:
        data = create_and_click(integration_client, url, 0)
        short_codes.append(data["short_code"])

    response = integration_client.get("/urls/recent")
    assert response.status_code == status.HTTP_200_OK

    items = response.json()["items"]
    assert len(items) == 3
    for item, expected_code in zip(items, reversed(short_codes)):
        assert item["short_code"] == expected_code


def test_top_urls_ordering(integration_client):
    list_of_urls = [["https://example.com", 5], ["https://new.com", 3]]
    for url, clicks in list_of_urls:
        create_and_click(integration_client, url, clicks)

    response = integration_client.get("/urls/top?period=1d")
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["count"] == 2
    for index, item in enumerate(body["items"]):
        assert item["long_url"] == list_of_urls[index][0] + "/"
        assert item["click_count"] == list_of_urls[index][1]


def test_search_by_long_url(integration_client):
    data = create_and_click(integration_client, "https://example.com/x", 0)

    response = integration_client.get("/urls/search", params={"long_url": "https://example.com/x"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["short_code"] == data["short_code"]

    response = integration_client.get("/urls/search", params={"long_url": "https://example.com/x/"})
    assert response.status_code == status.HTTP_200_OK

    response = integration_client.get("/urls/search", params={"long_url": "https://example.com/never-created"})
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_analytics_unknown_code_404(integration_client):
    response = integration_client.get("/urls/definitely-not-real/analytics")
    assert response.status_code == status.HTTP_404_NOT_FOUND



