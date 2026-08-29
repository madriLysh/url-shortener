import ipaddress
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Union, cast
from urllib.parse import urlparse, urlunparse

import tldextract
from redis import RedisError
from sqlalchemy import exists as sa_exists
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from user_agents import parse

from config import Config
from infrastructure import RedisClient
from log import get_logger
from models import URL, Click, ReferrerState
from utils import Base62

logger = get_logger(__name__)

class URLService:

    PREFIX = "url:"
    COUNTER_KEY = "global:counter"
    ALLOWED_SCHEMES = frozenset({'http', 'https'})
    BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})

    def __init__(self, redis_client: RedisClient, db_session: Session):
        self.redis = redis_client
        self.db = db_session

    def _key(self, short_code: str) -> str:
        return f'{self.PREFIX}{short_code}'

    def _is_url_expired(self, expires_at: Optional[datetime]) -> bool:
        if expires_at is None:
            return False

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return datetime.now(timezone.utc) > expires_at

    def _build_url_data_dict(
        self,
        url_obj: URL,
        short_code: Optional[str] = None,
        click_count: Optional[int] = None
    ) -> dict[str, str]:

        click_value = (
            click_count
            if click_count is not None
            else url_obj.click_count or 0
        )
        return {
            "id": str(url_obj.id),
            "short_code": short_code or url_obj.short_code,
            "long_url": url_obj.long_url,
            "expires_at": (
                url_obj.expires_at.isoformat()
                if url_obj.expires_at is not None
                else ""
            ),
            "click_count": str(click_value),
            "is_active": "True"
        }

    def _invalidate_if_deleted(self, cached: Optional[dict], key: str) -> Optional[dict]:
        if not cached:
            return None

        is_active_str = cached.get("is_active", "True")
        if is_active_str == "False":
            self.redis.delete(key)
            return None

        return cached

    def url_ever_existed(self, short_code: str) -> bool:
        result = self.db.query(
            sa_exists().where(URL.short_code == short_code)
        ).scalar()
        return bool(result)

    def get_url(self, short_code: str) -> Optional[dict[str, str]]:
        key = self._key(short_code)
        result = self.redis.get_hash(key)

        if result:
            result = self._invalidate_if_deleted(result, key)
            if result is None:
                return None

            if self._is_url_expired(
                datetime.fromisoformat(result.get("expires_at", ""))
                if result.get("expires_at") else None
            ):
                self.redis.delete(key)
                return None

            return result

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
        ).first()

        if not url:
            return None

        if self._is_url_expired(url.expires_at):
            setattr(url, 'is_active', False)
            self.db.commit()
            return None

        data = self._build_url_data_dict(url)
        self.redis.set_hash(key, data, ttl=Config.CACHE_TTL)
        return data

    def _generate_short_code(self) -> str:
        next_id = self.redis._execute("incr", self.COUNTER_KEY)
        if next_id is None:
            raise RedisError("Failed to generate short code: Redis unavailable")
        return Base62.encode(next_id)

    def _is_valid_code(self, code: str) -> bool:
        return (
            code.isalnum()
            and Config.MIN_CUSTOM_CODE_LENGTH <= len(code) <= Config.MAX_CUSTOM_CODE_LENGTH
        )

    def _code_exist(self, code: str, is_active: Optional[bool] = True) -> bool:
        cached = self.redis.get_hash(self._key(code))
        if cached:
            cached_is_active = cached.get("is_active", "True") == "True"
            if is_active is None or cached_is_active == is_active:
                return True
        query = self.db.query(URL).filter(URL.short_code == code)
        if is_active is not None:
            query = query.filter(URL.is_active == is_active)
        return query.first() is not None

    def create_url(
        self,
        long_url: str,
        creator_ip: str,
        expires_at: Optional[datetime] = None,
        custom_code: Optional[str] = None,
    ) -> tuple[str, str]:
        if not self._is_valid_long_url(long_url):
            raise ValueError(f"URL '{long_url}' is not allowed.")

        if custom_code:
            if not self._is_valid_code(custom_code):
                raise ValueError(
                    f"Custom code '{custom_code}' invalid. "
                    f"Use {Config.MIN_CUSTOM_CODE_LENGTH}-{Config.MAX_CUSTOM_CODE_LENGTH} "
                    f"alphanumeric characters."
                )

            token = self.redis.acquire_lock(
                f"code:{custom_code}",
                acquire_timeout=Config.REDIS_CONNECT_TIMEOUT,
            )
            if not token:
                raise ValueError(f"Could not acquire lock for '{custom_code}'. Try again.")

            try:
                if Config.ALLOW_REUSE_DELETED_CODES:
                    # Only active codes must not collide; deleted codes can be reused.
                    code_exists = self._code_exist(custom_code, is_active=True)
                else:
                    # Any record of the code, active or deleted, blocks reuse.
                    code_exists = self._code_exist(custom_code, is_active=None)

                if code_exists:
                    raise ValueError(f"Custom code '{custom_code}' already in use.")

                short_code = custom_code
            finally:
                self.redis.release_lock(f"code:{custom_code}", token)
        else:
            attempts = 0

            try:
                short_code = self._generate_short_code()
            except RedisError:
                raise RuntimeError("Could not generate short code: Redis unavailable")

            while self._code_exist(short_code) and attempts < Config.MAX_CODE_GENERATION_ATTEMPTS:
                try:
                    short_code = self._generate_short_code()
                except RedisError:
                    raise RuntimeError("Could not generate short code: Redis unavailable")
                attempts += 1

            if attempts >= Config.MAX_CODE_GENERATION_ATTEMPTS:
                raise RuntimeError("Could not generate unique code. Counter may be stuck.")

        url = URL(
            short_code=short_code,
            long_url=long_url,
            is_active=True,
            expires_at=expires_at,
            creator_ip=creator_ip,
        )
        self.db.add(url)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError(f"Short code '{short_code}' already exists.")

        data = self._build_url_data_dict(
            url,
            short_code=short_code,
            click_count=0
        )
        self.redis.set_hash(self._key(short_code), data, ttl=Config.CACHE_TTL)
        self.redis.zadd_and_trim(
            "recent_urls",
            short_code,
            time.time(),
            Config.RECENT_URLS_LIMIT
        )
        return short_code, url.edit_token

    def increment_clicks(self, short_code: str, ip_address: str) -> bool:
        key = self._key(short_code)
        cached = self.redis.get_hash(key)

        cached = self._invalidate_if_deleted(cached, key)

        if not cached:
            url = self.db.query(URL).filter(
                URL.short_code == short_code,
                URL.is_active == True
            ).first()
            if url:
                data = self._build_url_data_dict(url)
                self.redis.set_hash(key, data, ttl=Config.CACHE_TTL)
            else:
                return False

        self.redis.increment_hash_field(key, "click_count", 1)
        self.redis.pfadd(f"unique_visitors:{short_code}", ip_address)
        return True

    def delete_url(self, short_code: str) -> bool:
        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
        ).first()

        if not url:
            raise ValueError(f"URL '{short_code}' not found or already deleted.")

        setattr(url, 'is_active', False)

        pipe = self.redis.client.pipeline()
        pipe.delete(self._key(short_code))
        pipe.delete(f"referrers:{url.id}")
        pipe.zrem("recent_urls", short_code)

        try:
            pipe.execute()
        except Exception as e:
            logger.error(f"Failed to delete URL '{short_code}' from Redis: {e}", exc_info=True)
        self.db.commit()

        return True

    def restore_url(self, short_code: str) -> bool:

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == False
        ).first()

        if not url:
            raise ValueError(f"URL '{short_code}' not found or not deleted.")

        # Check if an ACTIVE URL has already claimed this code while it was deleted
        if self._code_exist(short_code):
            raise ValueError(f"Code '{short_code}' now used by another URL. Cannot restore.")

        setattr(url, 'is_active', True)
        self.db.commit()

        data = self._build_url_data_dict(url)
        self.redis.set_hash(self._key(short_code), data, ttl=Config.CACHE_TTL)

        return True

    def update_url(self, short_code: str, new_long_url: str, edit_token: str) -> bool:

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
        ).first()

        if not url:
            raise ValueError(f"URL '{short_code}' not found or deleted.")

        if url.edit_token != edit_token:
            raise ValueError("Invalid edit token. Unauthorized to update this URL.")

        url.long_url = new_long_url
        self.db.commit()

        data = self._build_url_data_dict(url)
        self.redis.set_hash(self._key(short_code), data, ttl=Config.CACHE_TTL)

        return True

    def get_recent_urls(self, offset: int = 0, limit: int = 10) -> list[str]:
        result = self.redis.zrevrange("recent_urls", offset, offset + limit - 1, scores=False)
        return result if result else []

    def _format_referrers(
        self,
        raw: Sequence[Union[tuple, ReferrerState]]
    ) -> list[dict[str, Union[str, int]]]:

        if not raw:
            return []

        formatted = []
        for item in raw:
            if isinstance(item, tuple):
                domain, score = item
                formatted.append({"domain": domain, "click_count": int(score)})
            else:
                referrer = cast(ReferrerState, item)
                formatted.append({
                    "domain": referrer.referrer_domain,
                    "click_count": referrer.click_count
                })

        return formatted

    def get_url_stats(self, short_code: str) -> Optional[dict]:

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
        ).first()

        if not url:
            return None

        pipe = self.redis.pipeline()
        pipe.hgetall(self._key(short_code))
        pipe.zrevrange(f"referrers:{url.id}", 0, Config.TOP_REFERRERS_LIMIT - 1, withscores=True)
        pipe.pfcount(f"unique_visitors:{short_code}")

        cached: Optional[dict] = None
        top_url = None

        try:
            results = pipe.execute()
            cached, top_url, unique_visitors = results[0], results[1], results[2]
        except Exception as e:
            logger.warning(f"Redis pipeline failed for stats, using DB fallback: {e}")
            cached = self.redis.get_hash(self._key(short_code))
            top_url, unique_visitors = None, None

        if not top_url:
            top_url = self.db.query(ReferrerState).filter(
                ReferrerState.url_id == url.id
            ).order_by(ReferrerState.click_count.desc()).limit(Config.TOP_REFERRERS_LIMIT).all()

        top_referrers = self._format_referrers(top_url)
        click_count = int(cached.get("click_count", 0)) if cached else url.click_count

        return {
            "short_code": url.short_code,
            "long_url": url.long_url,
            "click_count": click_count,
            "created_at": url.created_at.isoformat() if url.created_at is not None else None,
            "expires_at": url.expires_at.isoformat() if url.expires_at is not None else None,
            "source": "hybrid" if cached else "database",
            "top_referrers": top_referrers,
            "unique_visitors": unique_visitors or 0
        }

    def record_click(
        self,
        url_id: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        referrer: Optional[str],
    ) -> None:

        click = Click(
            url_id=int(url_id),
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer
        )
        self.db.add(click)
        try:
            self.db.commit()
        except Exception as e:
            logger.error("Failed to record click in DB: %s", e, exc_info=True)
            self.db.rollback()
            return

        # Referrer stats are derived/analytics data; keep them independent of the
        # core click record so a referrer failure does not lose the click.
        self._upsert_referrer(int(url_id), referrer)

    def _upsert_referrer(
        self,
        url_id: int,
        referrer: Optional[str],
    ) -> None:

        if not referrer:
            return

        referrer_domain = self._normalize_referrer(referrer)
        if not referrer_domain:
            return

        try:
            existing = (
                self.db.query(ReferrerState)
                .filter(
                    ReferrerState.url_id == url_id,
                    ReferrerState.referrer_domain == referrer_domain,
                )
                .first()
            )
            if existing:
                existing.click_count += 1
                existing.last_clicked = datetime.now(timezone.utc)
            else:
                new_referrer = ReferrerState(url_id=url_id, referrer_domain=referrer_domain)
                self.db.add(new_referrer)
            self.db.commit()
        except Exception as e:
            logger.error("Failed to update referrer in DB: %s", e, exc_info=True)
            self.db.rollback()

        try:
            self.redis.zincrby(f"referrers:{url_id}", referrer_domain, 1)
            self.redis.expire_nx(f"referrers:{url_id}", Config.CACHE_TTL)
        except Exception as e:
            logger.error(
                "Failed to update referrer stats in Redis for URL %d, domain %s: %s",
                url_id,
                referrer_domain,
                e,
                exc_info=True,
            )

    def _normalize_referrer(self, raw_url: str) -> Optional[str]:
        if not raw_url:
            return None

        try:
            extracted = tldextract.extract(raw_url)
            if not extracted.domain or not extracted.suffix:
                return None
            return f"{extracted.domain}.{extracted.suffix}".lower()
        except Exception:
            return None

    def sync_clicks_to_db(self) -> None:
        total_updated = 0
        error_batches = 0
        start_time = time.time()

        logger.info("Starting click sync to DB")

        def _sync_batch(keys: list[str]) -> Optional[int]:
            """Returns count of updated URLs, or None if the batch failed."""
            if not keys:
                return 0

            updated = 0

            try:
                pipe = self.redis.pipeline()
                for key in keys:
                    pipe.hgetall(key)
                results = pipe.execute()
            except Exception as e:
                logger.error(f"Redis error in batch: {e}")
                return None  # Fail batch, don't try fallback

            for data in results:
                if not data:
                    continue
                short_code = data.get("short_code")
                if not short_code:
                    continue

                click_count = int(data.get("click_count", 0))
                url = self.db.query(URL).filter(URL.short_code == short_code).first()

                if url and url.click_count != click_count:
                    url.click_count = click_count
                    updated += 1

            if updated > 0:
                try:
                    self.db.commit()
                    return updated
                except Exception as e:
                    logger.error(f"DB commit failed: {e}")
                    self.db.rollback()
                    return None
            else:
                self.db.rollback()
                return 0

        batch = []
        for key in self.redis.client.scan_iter(f"{self.PREFIX}*"):
            batch.append(key)
            if len(batch) >= Config.BATCH_SIZE:
                updated = _sync_batch(batch)
                if updated is None:
                    error_batches += 1
                else:
                    total_updated += updated
                batch.clear()

        if batch:
            updated = _sync_batch(batch)
            if updated is None:
                error_batches += 1
            else:
                total_updated += updated

        duration = time.time() - start_time

        logger.info(
            f"Sync complete: {total_updated} updated, {error_batches} error batches "
            f"in {duration:.2f}s"
        )

    def _is_valid_long_url(self, url: str) -> bool:
        """Basic SSRF guard: blocks literal private/loopback/link-local IPs and
        a small hostname blocklist.

        Note: this only inspects the parsed hostname. It does not resolve domains,
        so DNS-rebinding domains that point to private IPs are not blocked.
        """
        parsed = urlparse(url)
        if parsed.scheme not in self.ALLOWED_SCHEMES:
            return False

        hostname = parsed.hostname

        if not hostname or hostname in self.BLOCKED_HOSTNAMES:
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            pass
        return True

    def deactivate_expired_urls(self) -> int:
        expired_urls = self.db.query(URL).filter(
            URL.expires_at < datetime.now(timezone.utc),
            URL.is_active == True).limit(Config.EXPIRED_URLS_BATCH_SIZE).all()

        if not expired_urls:
            return 0

        short_codes = [url.short_code for url in expired_urls]
        redis_keys = [self._key(url.short_code) for url in expired_urls]
        url_ids = [url.id for url in expired_urls]

        pipe = self.redis.pipeline()

        for url in expired_urls:
            url.is_active = False
        self.db.commit()

        pipe.zrem("recent_urls", *short_codes)
        for key in redis_keys:
            pipe.delete(key)
        for url_id in url_ids:
            pipe.delete(f"referrers:{url_id}")
        try:
            pipe.execute()
        except Exception as e:
            logger.error(f"Failed to clean up expired URLs from Redis: {e}", exc_info=True)

        return len(expired_urls)

    def get_url_history(
        self,
        short_code: str,
        since: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 20
    ) -> Optional[dict]:

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True).first()
        if not url:
            return None

        query = self.db.query(Click).filter(Click.url_id == url.id)
        if since:
            query = query.filter(Click.clicked_at >= since)
        clicks = query.order_by(
            Click.clicked_at.desc()
        ).offset(offset).limit(limit).all()

        return {
            "short_code": url.short_code,
            "long_url": url.long_url,
            "clicks": [
                {
                    "clicked_at": click.clicked_at.isoformat(),
                    "user_agent": click.user_agent,
                    "referrer": click.referrer,
                    "country_code": click.country_code
                }
                for click in clicks
            ]
        }

    def extend_url_expiry(self, short_code: str, edit_token: str) -> int:

        url = self.db.query(URL).filter(URL.short_code == short_code, URL.is_active == True).first()
        if not url:
            raise ValueError(f"URL '{short_code}' not found or deleted.")
        if url.edit_token != edit_token:
            raise ValueError("Invalid edit token. Unauthorized to update this URL.")
        if not url.expires_at:
            raise ValueError("URL has no expiry to extend.")

        expires_at = url.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        new_expires_at = expires_at + timedelta(seconds=Config.CACHE_TTL)
        url.expires_at = new_expires_at
        self.db.commit()

        self.redis.update_hash_field(
            self._key(short_code),
            "expires_at",
            new_expires_at.isoformat())
        remaining = new_expires_at - datetime.now(timezone.utc)
        return int(remaining.total_seconds())

    def _parse_browser(self, user_agent: Optional[str]) -> str:
        if not user_agent:
            return "Unknown"
        try:
            parsed = parse(user_agent)
            return parsed.browser.family
        except Exception:
            return "Unknown"

    def _clicks_per_day(self, url: URL, since: Optional[datetime] = None):
        query = self.db.query(
            func.date(Click.clicked_at).label("date"),
            func.count().label("count")
        ).filter(Click.url_id == url.id)
        if since:
            query = query.filter(Click.clicked_at >= since)
        return query.group_by(
            func.date(Click.clicked_at)
        ).order_by(
            func.date(Click.clicked_at).desc()
        ).all()

    def _top_countries(self, url: URL, since: Optional[datetime] = None):
        query = self.db.query(
            Click.country_code,
            func.count().label("count")
        ).filter(Click.url_id == url.id)
        if since:
            query = query.filter(Click.clicked_at >= since)
        return query.group_by(
            Click.country_code
        ).order_by(
            func.count().desc()
        ).all()

    def _top_browsers(self, url: URL, since: Optional[datetime] = None):
        query = self.db.query(
            Click.user_agent,
            func.count().label("count")
        ).filter(Click.url_id == url.id)
        if since:
            query = query.filter(Click.clicked_at >= since)
        return query.group_by(
            Click.user_agent
        ).order_by(
            func.count().desc()
        ).all()

    def get_url_analytics(self, short_code: str, since: Optional[datetime] = None):

        url = self.db.query(URL).filter(
            URL.short_code == short_code,
            URL.is_active == True
            ).first()

        if not url:
            return None
        clicks_per_day = self._clicks_per_day(url, since)
        top_countries = self._top_countries(url, since)
        top_browsers = self._top_browsers(url, since)

        return {
            "clicks_per_day": [{
                "date": str(row.date),
                "count": row.count} for row in clicks_per_day],
            "top_countries": [{
                "country_code": row.country_code,
                "count": row.count} for row in top_countries],
            "top_browsers": [{
                "browser": self._parse_browser(row.user_agent),
                "count": row.count} for row in top_browsers],
        }

    def get_top_urls(
        self,
        since: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 10
    ) -> list[dict]:

        if since is None:
            urls = (
                self.db.query(URL)
                .filter(URL.is_active == True)
                .order_by(URL.click_count.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            return [
                {
                    "short_code": url.short_code,
                    "long_url": url.long_url,
                    "click_count": url.click_count,
                    "short_url": f"{Config.BASE_URL}/{url.short_code}"
                }
                for url in urls
            ]
        else:
            results = (
                self.db.query(
                    URL.short_code,
                    URL.long_url,
                    func.count(Click.id).label("click_count")
                )
                .select_from(URL)
                .join(Click, URL.id == Click.url_id)
                .filter(URL.is_active == True)
                .filter(Click.clicked_at >= since)
                .group_by(URL.id, URL.short_code, URL.long_url)
                .order_by(func.count(Click.id).desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "short_code": row.short_code,
                    "long_url": row.long_url,
                    "click_count": row.click_count,
                    "short_url": f"{Config.BASE_URL}/{row.short_code}"
                }
                for row in results
            ]

    def search_by_long_url(self, long_url: str) -> Optional[dict]:
        normalized = self._normalize_long_url(long_url)

        url = (
            self.db.query(URL)
            .filter(URL.long_url == normalized, URL.is_active == True)
            .first()
        )
        if not url:
            return None

        if self._is_url_expired(url.expires_at):
            setattr(url, 'is_active', False)
            self.db.commit()
            return None

        data = self._build_url_data_dict(url)
        self.redis.set_hash(self._key(url.short_code), data, ttl=Config.CACHE_TTL)

        return {
            "short_code": url.short_code,
            "long_url": url.long_url,
            "short_url": f"{Config.BASE_URL}/{url.short_code}",
            "click_count": url.click_count,
            "created_at": url.created_at.isoformat() if url.created_at else None,
            "expires_at": url.expires_at.isoformat() if url.expires_at else None,
        }

    def _normalize_long_url(self, url: str) -> str:

        parsed = urlparse(url.strip())

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        if ':80' in netloc and scheme == 'http':
            netloc = netloc.replace(':80', '')
        if ':443' in netloc and scheme == 'https':
            netloc = netloc.replace(':443', '')

        path = parsed.path.rstrip('/') or '/'
        query = parsed.query

        return urlunparse((scheme, netloc, path, '', query, ''))
