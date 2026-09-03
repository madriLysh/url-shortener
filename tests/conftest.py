from typing import Any, cast
from os import environ

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from infrastructure.database import Base
from infrastructure.redis_client import RedisClient
from services import URLService

class FakeRedis(RedisClient):
    """Minimal Redis stand-in for unit tests that never touch the network."""

    def __init__(self):
        self._data = {}
        self._counters = {}
        self._locks = {}
        self._scores = {}
        self._hyperloglog = {}
        # Some service code accesses redis.client.pipeline()
        super().__init__(cast(Redis, self))

    def get_hash(self, key):
        return self._data.get(key)

    def set_hash(self, key, data, ttl=None):
        self._data[key] = data
        return True

    def update_hash_field(self, key, field, value):
        if key not in self._data:
            self._data[key] = {}
        self._data[key][field] = value
        return True

    def increment_hash_field(self, key, field, amount=1):
        if key not in self._data:
            self._data[key] = {}
        current = int(self._data[key].get(field, 0))
        self._data[key][field] = str(current + amount)
        return True

    def pfadd(self, key, value):
        self._hyperloglog.setdefault(key, set()).add(value)
        return True

    def pfcount(self, key):
        return len(self._hyperloglog.get(key, set()))

    def delete(self, key):
        self._data.pop(key, None)
        return True

    def _execute(self, operation, *args, **kwargs):
        if operation == "incr":
            key = args[0]
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]
        return None

    def acquire_lock(self, lock_name, acquire_timeout=10, lock_timeout=10):
        if lock_name in self._locks:
            return None
        token = "token"
        self._locks[lock_name] = token
        return token

    def release_lock(self, lock_name, token):
        self._locks.pop(lock_name, None)
        return True

    def zadd_and_trim(self, key, member, score, limit):
        return True

    def zrem(self, key, member):
        return True

    def zincrby(self, key, member, increment=1):
        self._scores.setdefault(key, {})
        self._scores[key][member] = self._scores[key].get(member, 0) + increment
        return True

    def zrevrange(self, key, start=0, end=9, scores=False):
        # Sort by score descending, then by member reverse-alphabetically to match
        # real Redis ZREVRANGE tie-breaking.
        items = sorted(
            self._scores.get(key, {}).items(),
            key=lambda x: (x[1], x[0]),
            reverse=True,
        )
        if end < 0:
            end = len(items) + end
        else:
            end = min(end, len(items) - 1)
        start = max(start, 0)
        if start > end:
            return []
        sliced = items[start:end + 1]
        if scores:
            return [(member, score) for member, score in sliced]
        return [member for member, _ in sliced]

    def expire_nx(self, key, ttl):
        return True

    def pipeline(self):
        return cast(Any, self)

    def execute(self):
        return []

    def rate_limit(self, key, max_requests, window_seconds):
        return (True, 1)

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def service(db_session):
    return URLService(redis_client=FakeRedis(), db_session=db_session)

@pytest.fixture
def real_redis():
    if not (url := environ.get("REDIS_TEST_URL")):
        pytest.skip("set REDIS_TEST_URL to run real-Redis tests")
    raw = Redis.from_url(url, decode_responses=True)
    raw.ping()
    raw.flushdb()

    try:
        yield RedisClient(raw)
    finally:
        raw.flushdb()
        raw.close()