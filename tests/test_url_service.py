from datetime import datetime, timezone, timedelta
import pytest

from config import Config
from models import Click, URL
from conftest import FakeRedis




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

def test_increment_clicks_cache_hit_increments_and_tracks_visitor(service):
    service.redis._data["url:clk1"] = {
        "id": "4",
        "short_code": "clk1",
        "long_url": "https://example.com",
        "expires_at": "",
        "click_count": "5",
        "is_active": "True"
    }
    result = service.increment_clicks("clk1", "1.2.3.4")
    assert result is True
    assert service.redis._data["url:clk1"]["click_count"] == "6"
    assert "1.2.3.4" in service.redis._hyperloglog["unique_visitors:clk1"]

def test_increment_clicks_cache_miss_backfills_then_increments(service, db_session):
    db_session.add(URL(
        short_code="clk2",
        long_url="https://example.com",
        is_active=True,
        expires_at=None,
        edit_token="tok"
    ))
    db_session.commit()

    assert "url:clk2" not in service.redis._data 
    result = service.increment_clicks("clk2", "1.2.3.4")
    assert result is True
    assert service.redis._data["url:clk2"]["click_count"] == "1"
    assert "1.2.3.4" in service.redis._hyperloglog["unique_visitors:clk2"]

def test_increment_clicks_unknown_code_returns_false(service):
    result = service.increment_clicks("ghost1", "9.9.9.9")
    assert result is False
    assert "url:ghost1" not in service.redis._data 
    assert "unique_visitors:ghost1" not in service.redis._hyperloglog

def test_update_url_valid_token_updates_db_and_cache(service, db_session):
    db_session.add(URL(
        short_code="up1",
        long_url="https://old.com",
        is_active=True,
        expires_at=None,
        edit_token="secret-tok"
    ))
    db_session.commit()

    result = service.update_url("up1", "https://new.com", "secret-tok")
    assert result is True

    row = db_session.query(URL).filter(URL.short_code == "up1").first()
    assert row.long_url == "https://new.com"
    assert "https://new.com" == service.redis._data["url:up1"]["long_url"]

def test_update_url_invalid_token_raises_and_leaves_url_unchanged(service, db_session):
    db_session.add(URL(
        short_code="up2",
        long_url="https://old.com",
        is_active=True,
        expires_at=None,
        edit_token="secret-tok"
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="Invalid edit token"):
        service.update_url("up2", "https://new.com", "wrong-tok")
    assert "url:up2" not in service.redis._data

    row = db_session.query(URL).filter(URL.short_code == "up2").first()
    assert row.long_url == "https://old.com"
    
def test_update_url_unknown_code_raises_not_found(service):
    with pytest.raises(ValueError, match="not found"):
        service.update_url("ghost", "https://new.com", "tok")

def test_restore_url_deleted_row_restores_and_backfills_cache(service, db_session):
    db_session.add(URL(
        short_code="rs1",
        long_url="https://example.com",
        is_active=False,
        expires_at=None,
        edit_token="tok"
    ))
    db_session.commit()

    assert "url:rs1" not in service.redis._data 

    result = service.restore_url("rs1")
    assert result is True
    assert service.redis._data["url:rs1"]["is_active"] == "True"
    assert service.redis._data["url:rs1"]["long_url"] == "https://example.com"

def test_restore_url_active_row_raises(service, db_session):
    db_session.add(URL(
        short_code="rs2",
        long_url="https://example.com",
        is_active=True,
        expires_at=None,
        edit_token="tok"
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="not found or not deleted"):
        service.restore_url("rs2")

    row = db_session.query(URL).filter(URL.short_code == "rs2").first()
    assert row.is_active == True

def test_restore_url_unknown_code_raises(service):
    with pytest.raises(ValueError, match="not found"):
        service.restore_url("rs3")

def test_restore_url_reclaimed_code_raises(service, db_session):
    db_session.add(URL(
        short_code= "rs4",
        long_url="https://example.com",
        is_active=True,
        expires_at=None,
        edit_token="t1"
    ))
    db_session.add(URL(
        short_code= "rs4",
        long_url="https://example.com",
        is_active=False,
        expires_at=None,
        edit_token="t2"
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="now used by another URL"):
        service.restore_url("rs4")

    row = db_session.query(URL).filter(URL.edit_token == "t2").first()
    assert row.is_active == False

def test_extend_url_expiry_unknown_code_raises(service):
    with pytest.raises(ValueError, match="not found"):
        service.extend_url_expiry("ghost", "tok")

def test_extend_url_expiry_invalid_token_raises(service):
    short_code, _ = service.create_url(
        "https://example.com",
        creator_ip="1.2.3.4",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    with pytest.raises(ValueError, match="Invalid edit token"):
        service.extend_url_expiry(short_code, "wrong-token")

def test_extend_url_expiry_no_expiry_raises(service):
    short_code, edit_token = service.create_url(
        "https://example.com",
        creator_ip="1.2.3.4"
    )

    with pytest.raises(ValueError, match="no expiry to extend"):
        service.extend_url_expiry(short_code, edit_token)

def test_create_url_lock_unavailable_raises(service):
    service.redis._locks["code:token1"] = "someone-elses-token" 

    with pytest.raises(ValueError, match="Could not acquire lock"):
        service.create_url("https://example.com", creator_ip="1.2.3.4", custom_code="token1")

def test_create_url_counter_unavailable_raises_runtime_error(service, monkeypatch):
    monkeypatch.setattr(service.redis, "_execute", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="Could not generate short code"):
        service.create_url("https://example.com", creator_ip="1.2.3.4")

def test_create_url_collision_exhaustion_raises_runtime_error(service, monkeypatch):
    monkeypatch.setattr(service, "_code_exist", lambda code, is_active=True: True)

    with pytest.raises(RuntimeError, match="Could not generate unique code"):
        service.create_url("https://example.com", creator_ip="1.2.3.4")

@pytest.mark.parametrize("exp_date, expected", (
    (None, False),
    (datetime(2000, 1, 1, tzinfo=timezone.utc), True),
    (datetime(2099, 1, 1, tzinfo=timezone.utc), False),
    (datetime(2000, 1, 1), True),
    (datetime(2099, 1, 1), False)
))
def test_is_url_expired(service, exp_date, expected):
    assert expected is service._is_url_expired(exp_date)

@pytest.mark.parametrize("code, expected", (
    ("ab", False),
    ("abc", True),
    ("a" * 20, True),
    ("a" * 21, False), 
    ("ab!", False),
    ("", False)
))
def test_is_valid_code(service, code, expected):
    assert expected is service._is_valid_code(code)

@pytest.mark.parametrize("url, expected", (
    ("https://www.twitter.com/user/1", "twitter.com"),
    ("https://blog.example.co.uk/page", "example.co.uk"),
    ("twitter.com", "twitter.com"),
    ("localhost", None),
    ("", None),
    ("https://192.168.1.1/admin", None)
))
def test_normalize_referrer(service, url, expected):
    assert expected == service._normalize_referrer(url)

@pytest.mark.parametrize("url, expected",(
    ("HTTP://EXAMPLE.COM", "http://example.com/"),
    ("http://example.com:80/path", "http://example.com/path"),
    ("https://example.com:443/", "https://example.com/"),
    ("https://example.com/path/", "https://example.com/path"),
    ("https://example.com?a=1&b=2", "https://example.com/?a=1&b=2"),
    ("  https://example.com/x  ", "https://example.com/x")
))
def test_normalize_long_url(service, url, expected):
    assert expected == service. _normalize_long_url(url)

@pytest.mark.parametrize("seed, expected",(
        (None, False),
        (True, True),
        (False, True)
))
def test_url_ever_existed(service, db_session, seed, expected):
    if seed is None:
        assert expected is service.url_ever_existed("ghost")
        return
    db_session.add(URL(
        short_code="url",
        long_url="https://example.com",
        is_active=seed,
        expires_at=None,
        edit_token="tok"
    ))
    db_session.commit()
    assert expected is service.url_ever_existed("url")

def test_get_recent_urls_returns_ordered_window(service):
    service.redis._scores["recent_urls"] = {"aaa": 100.0, "bbb": 200.0, "ccc": 300.0}
    assert service.get_recent_urls(0, 2) == ["ccc", "bbb"]
    assert service.get_recent_urls(1, 2) == ["bbb", "aaa"]

def test_delete_url_unknown_code_raises(service):
    with pytest.raises(ValueError, match="not found"):
        service.delete_url("unknown")

def test_delete_url_active_row_deactivates_and_evicts(service, db_session):
    db_session.add(URL(
        short_code="dl1",
        long_url="https://example.com",
        is_active=True,
        expires_at=None,
        edit_token="tok"
    ))
    db_session.commit()

    service.redis._data["url:dl1"] = {
    "id": "1", "short_code": "dl1", "long_url": "https://example.com",
    "expires_at": "", "click_count": "0", "is_active": "True",
    }

    result = service.delete_url("dl1")
    assert result is True

    row = db_session.query(URL).filter(URL.short_code == "dl1").first()
    assert row.is_active is False
    assert "url:dl1" not in service.redis._data 
