import pytest

from infrastructure.redis_client import RedisClient

pytestmark = [pytest.mark.redis]

def test_zadd_and_trim_keeps_newest_within_limit(real_redis: RedisClient):
    for i in range(5):
        result = real_redis.zadd_and_trim("recent:trim", member=f"m{i}", score=i, limit=3)
        assert result is True

    assert real_redis.zrevrange("recent:trim",  0, -1) == ["m4", "m3", "m2"]

def test_zadd_and_trim_under_limit_keeps_all(real_redis: RedisClient):
    for i in range(3):
        result = real_redis.zadd_and_trim("recent:under_limit", member=f"m{i}", score=i, limit=5)
        assert result is True
    
    assert real_redis.zrevrange("recent:under_limit",  0, -1) == ["m2", "m1", "m0"]