from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from config import Config
from infrastructure import RedisClient, get_db
from services import URLService


def get_redis_client() -> RedisClient:
    return RedisClient.from_pool()

def get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For if behind a proxy."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def get_url_service(
    db: Session = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client)
) -> URLService:
    return URLService(redis, db)

def verify_api_key(
    x_api_key: Optional[str] = Header(default=None)
) -> None:
    if not Config.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key not configured."
        )
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header missing."
            )
    if x_api_key != Config.ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key.")

def check_rate_limit(redis: RedisClient, key: str, max_requests: int, window: int):
    allowed, _ = redis.rate_limit(key=key, max_requests=max_requests, window_seconds=window)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: max {max_requests} requests per {window}s."
        )

def rate_limit_for(endpoint: str, limit_type: str):
    def check(redis: RedisClient, client_ip: str):
        limits = {
            "read": Config.RATE_LIMIT_READS,
            "write": Config.RATE_LIMIT_WRITES,
            "redirect": Config.RATE_LIMIT_REDIRECTS,
            "create": Config.RATE_LIMIT_REQUESTS,
        }
        max_limit = limits.get(limit_type, Config.RATE_LIMIT_READS)
        check_rate_limit(
            redis,
            f"rate:{endpoint}:{client_ip}",
            max_limit,
            Config.RATE_LIMIT_WINDOW
        )
    return check

def since_calculation(period: Optional[str] = Query(None, description="1d, 1w, 1m, 3m, 1y")):
    periods = {
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "3m": timedelta(days=90),
        "1y": timedelta(days=365),
    }
    return datetime.now(timezone.utc) - periods[period] if period in periods else None

def check_rate_limit_read(redis: RedisClient, endpoint: str, client_ip: str):
    rate_limit_for(endpoint, "read")(redis, client_ip)

def check_rate_limit_write(redis: RedisClient, endpoint: str, client_ip: str):
    rate_limit_for(endpoint, "write")(redis, client_ip)

def check_rate_limit_redirect(redis: RedisClient, client_ip: str):
    rate_limit_for("redirect", "redirect")(redis, client_ip)

def check_rate_limit_create(redis: RedisClient, client_ip: str):
    rate_limit_for("create", "create")(redis, client_ip)
