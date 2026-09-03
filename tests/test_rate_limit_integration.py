import pytest
from infrastructure.redis_client import RedisClient

pytestmark = [pytest.mark.redis]

def test_redis_connection_alive(real_redis: RedisClient):
    response = real_redis.client.ping()
    assert response is True