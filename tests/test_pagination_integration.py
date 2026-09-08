import pytest
from fastapi import status

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def create_short_url(integration_client, long_url: str, index: int) -> dict:
    # /shorten is rate-limited per client IP (default 10/min); vary the
    # forwarded IP so seeding 15 URLs in one test stays under the limit.
    response = integration_client.post(
        "/shorten",
        json={"long_url": long_url},
        headers={"X-Forwarded-For": f"10.0.0.{index}"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def click(integration_client, short_code: str, times: int, user_agent: str = "agent") -> None:
    for _ in range(times):
        response = integration_client.get(
            f"/{short_code}",
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_302_FOUND


def seed_ranked_urls(integration_client, click_counts: list[int]) -> list[dict]:
    seeded = []
    for index, clicks in enumerate(click_counts):
        data = create_short_url(
            integration_client, f"https://example.com/ranked-{index}", index
        )
        click(integration_client, data["short_code"], clicks)
        seeded.append(data)
    return seeded


def test_recent_pagination_no_overlap_between_pages(integration_client):
    created_codes = []
    for i in range(15):
        data = create_short_url(integration_client, f"https://example.com/recent-{i}", i)
        created_codes.append(data["short_code"])

    page1 = integration_client.get("/urls/recent", params={"page": 1, "page_size": 10})
    assert page1.status_code == status.HTTP_200_OK
    body1 = page1.json()
    assert body1["page"] == 1
    assert body1["page_size"] == 10
    assert body1["count"] == 10
    assert len(body1["items"]) == 10

    page2 = integration_client.get("/urls/recent", params={"page": 2, "page_size": 10})
    assert page2.status_code == status.HTTP_200_OK
    body2 = page2.json()
    assert body2["page"] == 2
    assert body2["page_size"] == 10
    assert body2["count"] == 5
    assert len(body2["items"]) == 5

    codes_page1 = {item["short_code"] for item in body1["items"]}
    codes_page2 = {item["short_code"] for item in body2["items"]}
    assert codes_page1.isdisjoint(codes_page2)
    assert codes_page1 | codes_page2 == set(created_codes)

    for item in body1["items"] + body2["items"]:
        assert set(item.keys()) == {"short_code", "short_url", "long_url"}


def test_recent_page_beyond_available_data_is_empty(integration_client):
    for i in range(3):
        create_short_url(integration_client, f"https://example.com/beyond-{i}", i)

    response = integration_client.get("/urls/recent", params={"page": 2, "page_size": 10})
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["page"] == 2


def test_history_pagination_no_overlap_between_pages(integration_client):
    data = create_short_url(integration_client, "https://example.com/history", 0)

    agents = [f"agent-{i:02d}" for i in range(15)]
    for agent in agents:
        click(integration_client, data["short_code"], 1, user_agent=agent)

    page1 = integration_client.get(
        f"/urls/{data['short_code']}/history", params={"page": 1, "page_size": 10}
    )
    assert page1.status_code == status.HTTP_200_OK
    body1 = page1.json()
    assert body1["short_code"] == data["short_code"]
    assert body1["page"] == 1
    assert body1["page_size"] == 10
    assert body1["count"] == 10

    page2 = integration_client.get(
        f"/urls/{data['short_code']}/history", params={"page": 2, "page_size": 10}
    )
    assert page2.status_code == status.HTTP_200_OK
    body2 = page2.json()
    assert body2["page"] == 2
    assert body2["count"] == 5

    agents_page1 = {item["user_agent"] for item in body1["items"]}
    agents_page2 = {item["user_agent"] for item in body2["items"]}
    assert agents_page1.isdisjoint(agents_page2)
    assert agents_page1 | agents_page2 == set(agents)

    for item in body1["items"]:
        assert set(item.keys()) == {"clicked_at", "user_agent", "referrer", "country_code"}


def test_top_urls_limit_param_controls_item_count(integration_client):
    seeded = seed_ranked_urls(integration_client, [5, 3, 1])

    response = integration_client.get("/urls/top", params={"period": "1d", "limit": 2})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["count"] == 2
    assert [item["click_count"] for item in body["items"]] == [5, 3]
    assert body["items"][0]["short_code"] == seeded[0]["short_code"]

    response = integration_client.get("/urls/top", params={"period": "1d", "limit": 3})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["count"] == 3
    assert [item["click_count"] for item in body["items"]] == [5, 3, 1]


def test_top_urls_page_and_page_size_offset_results(integration_client):
    seeded = seed_ranked_urls(integration_client, [5, 3, 1])

    page1 = integration_client.get(
        "/urls/top", params={"period": "1d", "limit": 1, "page": 1, "page_size": 1}
    )
    assert page1.status_code == status.HTTP_200_OK
    body1 = page1.json()
    assert body1["count"] == 1
    assert body1["items"][0]["short_code"] == seeded[0]["short_code"]

    page2 = integration_client.get(
        "/urls/top", params={"period": "1d", "limit": 1, "page": 2, "page_size": 1}
    )
    assert page2.status_code == status.HTTP_200_OK
    body2 = page2.json()
    assert body2["count"] == 1
    assert body2["items"][0]["short_code"] == seeded[1]["short_code"]

    assert body1["items"][0]["short_code"] != body2["items"][0]["short_code"]


def test_top_urls_page_size_does_not_limit_items(integration_client):
    # /urls/top passes only `limit` (default 10) to the service; page_size
    # affects the offset but never the number of items returned.
    seed_ranked_urls(integration_client, [5, 3, 1])

    response = integration_client.get("/urls/top", params={"period": "1d", "page_size": 2})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["page_size"] == 2
    assert body["count"] == 3
    assert len(body["items"]) == 3

    response = integration_client.get(
        "/urls/top", params={"period": "1d", "page": 2, "page_size": 1}
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["count"] == 2
    assert [item["click_count"] for item in body["items"]] == [3, 1]
