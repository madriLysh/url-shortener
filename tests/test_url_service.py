from typing import Any, cast
from datetime import datetime, timezone

import pytest
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from infrastructure.database import Base
from infrastructure.redis_client import RedisClient
from models import Click, URL
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


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
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


@pytest.mark.parametrize("url, allowed", [
    ("https://example.com/path", True),
    ("http://example.com", True),
    ("https://www.google.com/search?q=test", True),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("http://localhost:8000/shorten", False),
    ("http://127.0.0.1/secret", False),
    ("http://[::1]/", False),
    ("http://10.0.0.5/private", False),
    ("http://192.168.1.1/", False),
    ("http://metadata.google.internal/", False),
    ("ftp://example.com/file", False),
    ("not-a-url", False),
])
def test_is_valid_long_url(service, url, allowed):
    assert service._is_valid_long_url(url) is allowed


def test_create_url_rejects_private_url(service):
    with pytest.raises(ValueError, match="is not allowed"):
        service.create_url("http://127.0.0.1/admin", creator_ip="127.0.0.1")


def test_create_url_with_reused_deleted_code_when_allowed(service, monkeypatch):
    monkeypatch.setattr(Config, "ALLOW_REUSE_DELETED_CODES", True)

    service.create_url("https://example.com", creator_ip="1.2.3.4", custom_code="reuse")
    service.delete_url("reuse")

    short_code, _ = service.create_url(
        "https://example.org", creator_ip="1.2.3.4", custom_code="reuse"
    )
    assert short_code == "reuse"


def test_create_url_rejects_active_custom_code(service):
    service.create_url("https://example.com", creator_ip="1.2.3.4", custom_code="taken")

    with pytest.raises(ValueError, match="already in use"):
        service.create_url(
            "https://example.org", creator_ip="1.2.3.4", custom_code="taken"
        )


def test_create_url_rejects_deleted_code_when_reuse_disabled(service, monkeypatch):
    monkeypatch.setattr(Config, "ALLOW_REUSE_DELETED_CODES", False)

    service.create_url("https://example.com", creator_ip="1.2.3.4", custom_code="noreuse")
    service.delete_url("noreuse")

    with pytest.raises(ValueError, match="already in use"):
        service.create_url(
            "https://example.org", creator_ip="1.2.3.4", custom_code="noreuse"
        )


def test_extend_url_expiry(service):
    from datetime import datetime, timedelta, timezone

    short_code, edit_token = service.create_url(
        "https://example.com",
        creator_ip="1.2.3.4",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )

    remaining = service.extend_url_expiry(short_code, edit_token)
    assert remaining > 60


def test_record_click_survives_referrer_failure(service, monkeypatch):
    short_code, _ = service.create_url("https://example.com", creator_ip="1.2.3.1")
    url = service.db.query(URL).filter(URL.short_code == short_code).first()

    original_commit = service.db.commit
    commit_calls = []

    def flaky_commit(*args, **kwargs):
        commit_calls.append(1)
        if len(commit_calls) > 1:  # second commit is the referrer upsert
            raise RuntimeError("referrer db boom")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(service.db, "commit", flaky_commit)

    # Should not raise; the core click must still be recorded
    service.record_click(str(url.id), "1.2.3.1", "agent", "https://referrer.com")

    service.db.rollback()
    clicks = service.db.query(Click).filter(Click.url_id == url.id).all()
    assert len(clicks) == 1


def test_fake_redis_zrevrange_tie_breaking():
    redis = FakeRedis()
    redis.zincrby("referrers:1", "google.com", 1)
    redis.zincrby("referrers:1", "twitter.com", 1)

    result = redis.zrevrange("referrers:1", 0, -1)
    assert result == ["twitter.com", "google.com"]

def test_get_url_cache_hit_fresh(service):
    service.redis._data["url:fresh1"] = {
        "id": "1",
        "short_code": "fresh1",
        "long_url": "https://example.com",
        "expires_at": "", 
        "click_count": "0",
        "is_active": "True"
    }

    result = service.get_url("fresh1")
    assert result is not None
    assert result["long_url"]== "https://example.com"

def test_get_url_cache_hit_inactive_evicts_entr(service):
    service.redis._data["url:gone1"] = {
        "id": "2",
        "short_code": "gone1",
        "long_url": "https://example.com",
        "expires_at": "",
        "click_count": "0",
        "is_active": "False"
    }

    result = service.get_url("gone1")
    assert result is None
    assert "url:gone1" not in service.redis._data

def test_get_url_cache_hit_expired_evicts_entry(service):
    service.redis._data["url:exp1"] = {
        "id": "3",
        "short_code": "exp1",
        "long_url": "https://example.com",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "click_count": "0",
        "is_active": "True",
    }

    result = service.get_url("exp1")

    assert result is None
    assert "url:exp1" not in service.redis._data

def test_get_url_cache_miss_db_hit_backfills(service, db_session):
    db_session.add(URL(
        short_code="dbok1",
        long_url="https://example.com/page",
        is_active=True,
        expires_at=None,
        edit_token="tok",
    ))
    db_session.commit()

    assert "url:dbok1" not in service.redis._data

    result = service.get_url("dbok1")
    assert result is not None
    assert result["long_url"] == "https://example.com/page"

def test_get_url_cache_miss_expired_db_row_deactivates(service, db_session):
    expires_at = datetime(2000,1,1,tzinfo=timezone.utc)
    db_session.add(URL(
        id=1,
        short_code="dbexp1",
        long_url="https://example.com/page",
        is_active=True,
        expires_at= expires_at,
        edit_token="Tok",
    ))
    db_session.commit()

    assert "url:dbexp1" not in service.redis._data 

    result = service.get_url("dbexp1")

    assert result is None

    row = db_session.query(URL).filter(URL.short_code == "dbexp1").first()
    assert row is not None
    assert row.is_active is False

def test_get_url_total_miss_returns_none(service):
    result = service.get_url("none1")
    assert result is None