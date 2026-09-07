import pytest
from fastapi import status
from datetime import date
pytestmark = [pytest.mark.integration, pytest.mark.redis]

def create_and_click(integration_client, url: str, times: int) -> dict:
    response = integration_client.post("/shorten", json={"long_url": url})
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    for _ in range(times):
        integration_client.get(f"/{data['short_code']}", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] ==  data["long_url"]
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

    days = response.json()["clicks_per_day"]
    countries = response.json()["top_countries"]
    browsers = response.json()["top_browsers"]

    assert days == []
    assert countries == []
    assert browsers == []
    
def test_history_returns_clicks(integration_client):
    response = integration_client.post("/shorten", json={"long_url": "https://example.com"})
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()

    for agent in ["agent-a", "agent-b"]:
        integration_client.get(f"/{data['short_code']}", follow_redirects=False, headers={"user-Agent": agent})
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] ==  data["long_url"]

    response = integration_client.get(f"/urls/{data['short_code']}/history", follow_redirects=False)
    assert response.status_code == status.http
        
    

