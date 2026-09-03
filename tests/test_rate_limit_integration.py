import pytest
from time import sleep

from redis import Redis
from infrastructure.redis_client import RedisClient
from fastapi.testclient import TestClient
from fastapi import status

from main import build_application
from config import Config
from services import URLService
from api.dependencies import get_url_service

pytestmark = [pytest.mark.redis]

MAX_REQUESTS = 3
WINDOW_SECONDS = 2


def rl_key(name: str) -> str:
    return f"url:test:{name}"


def rate_limit_helper(real_redis: RedisClient, name: str) -> tuple[bool, int]:
    return real_redis.rate_limit(
        rl_key(name=name),
        max_requests=MAX_REQUESTS,
        window_seconds=WINDOW_SECONDS,
    )


def call_n_times(real_redis: RedisClient, name: str, n: int) -> list[tuple[bool, int]]:
    return [rate_limit_helper(real_redis, name) for _ in range(n)]


def test_redis_connection_alive(real_redis: RedisClient):
    response = real_redis.client.ping()
    assert response is True


def test_rate_limit_allows_under_limit(real_redis: RedisClient):
    allowed, count = rate_limit_helper(real_redis=real_redis, name="under_limit")
    assert allowed is True
    assert count == 1


def test_rate_limit_counts_increment(real_redis: RedisClient):
    results = call_n_times(real_redis=real_redis, name="counts_increment", n=MAX_REQUESTS)

    assert all(allowed is True for allowed, _ in results)
    assert [count for _, count in results] == [1, 2, 3]


def test_rate_limit_denies_over_max(real_redis: RedisClient):
    results = call_n_times(real_redis=real_redis, name="over_max", n=MAX_REQUESTS + 1)

    assert all(allowed is True for allowed, _ in results[:MAX_REQUESTS])
    assert [count for _, count in results[:MAX_REQUESTS]] == [1, 2, 3]
    assert results[-1] == (False, MAX_REQUESTS + 1)


def test_rate_limit_resets_after_window(real_redis: RedisClient):
    call_n_times(real_redis=real_redis, name="reset_window", n=MAX_REQUESTS)

    sleep(2.1)

    allowed, count = rate_limit_helper(real_redis=real_redis, name="reset_window")
    assert allowed is True
    assert count == 1


def test_rate_limit_keys_are_independent(real_redis: RedisClient):
    call_n_times(real_redis=real_redis, name="key_a", n=MAX_REQUESTS)

    allowed, count = rate_limit_helper(real_redis=real_redis, name="key_b")
    assert allowed is True
    assert count == 1


def test_rate_limit_fail_open_on_redis_error():
    dead = RedisClient(Redis(host="localhost", port=6390,
                             socket_connect_timeout=0.1, socket_timeout=0.1))
    allowed, count = dead.rate_limit(rl_key("fail_open"), MAX_REQUESTS, WINDOW_SECONDS)
    assert allowed is True
    assert count == 0


@pytest.fixture
def integration_client(service: URLService, real_redis: RedisClient):
    # The /shorten rate-limit path reads service.redis (api/routes.py:35-38),
    # so point the service fixture's redis at the real Redis. SQLite stays.
    # Safe only because `service` is function-scoped — a wider scope would leak this
    # mutation into other tests.
    service.redis = real_redis
    app = build_application()
    app.dependency_overrides[get_url_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_shorten_returns_429_over_limit(integration_client: TestClient, monkeypatch):
    monkeypatch.setattr(Config, "RATE_LIMIT_REQUESTS", MAX_REQUESTS)
    monkeypatch.setattr(Config, "RATE_LIMIT_WINDOW", WINDOW_SECONDS)

    for i in range(MAX_REQUESTS):
        response = integration_client.post(
            "/shorten", json={"long_url": f"https://example.com/page{i}"}
        )
        assert response.status_code == status.HTTP_201_CREATED

    response = integration_client.post(
        "/shorten", json={"long_url": "https://example.com/overflow"}
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.json()["detail"] == (
        f"Rate limit exceeded: max {MAX_REQUESTS} requests per {WINDOW_SECONDS}s."
    )
