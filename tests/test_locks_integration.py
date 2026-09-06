import pytest
from time import sleep

from infrastructure.redis_client import RedisClient

pytestmark = [pytest.mark.redis]


def acquire(real_redis: RedisClient, name: str, lock_timeout: int = 10) -> str:
    """Setup helper: acquire a lock and assert success. Never the thing under test."""
    token = real_redis.acquire_lock(f"test:{name}", acquire_timeout=1, lock_timeout=lock_timeout)
    assert token is not None
    return token


def test_acquire_lock_returns_token(real_redis: RedisClient):
    result = real_redis.acquire_lock("test:basic", acquire_timeout=1, lock_timeout=2)
    assert result is not None


def test_acquire_lock_contention_returns_none(real_redis: RedisClient):
    acquire(real_redis=real_redis, name="contention")

    result = real_redis.acquire_lock("test:contention", acquire_timeout=1, lock_timeout=10)
    assert result is None


def test_release_lock_with_correct_token(real_redis: RedisClient):
    token = acquire(real_redis=real_redis, name="release_ok")

    released = real_redis.release_lock("test:release_ok", token)
    assert released is True

    result = real_redis.acquire_lock("test:release_ok", acquire_timeout=1, lock_timeout=10)
    assert result is not None


def test_release_lock_with_wrong_token_fails(real_redis: RedisClient):
    acquire(real_redis=real_redis, name="release_bad")

    released = real_redis.release_lock("test:release_bad", "wrong_token")
    assert released is False

    # lock must survive a wrong-token release — direct call, NOT the helper
    result = real_redis.acquire_lock("test:release_bad", acquire_timeout=1, lock_timeout=10)
    assert result is None


def test_lock_expires_after_timeout(real_redis: RedisClient):
    acquire(real_redis=real_redis, name="expiry", lock_timeout=1)

    sleep(1.1)

    token = real_redis.acquire_lock("test:expiry", acquire_timeout=1, lock_timeout=10)
    assert token is not None


def test_extend_lock_with_correct_token(real_redis: RedisClient):
    token = acquire(real_redis=real_redis, name="extend_ok", lock_timeout=5)

    ttl_before = real_redis.client.ttl("lock:test:extend_ok")

    extended = real_redis.extend_lock("test:extend_ok", token, 10)
    assert extended is True

    ttl_after = real_redis.client.ttl("lock:test:extend_ok")
    assert ttl_after > ttl_before # type: ignore


def test_extend_lock_with_wrong_token_fails(real_redis: RedisClient):
    acquire(real_redis=real_redis, name="extend_bad")

    extended = real_redis.extend_lock("lock:test:extend_bad", "wrong_token", 1)
    assert extended is False
