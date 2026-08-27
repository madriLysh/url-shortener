from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies import get_redis_client
from infrastructure import RedisClient, get_db

router = APIRouter(prefix="/health")

@router.get("")
def health_check(
    response: Response,
    redis: RedisClient = Depends(get_redis_client),
    db: Session = Depends(get_db)
):
    status = {"status": "ok", "redis": "ok", "database": "ok"}

    try:
        redis.client.ping()
    except Exception:
        status["redis"] = "unavailable"
        status["status"] = "degraded"

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        status["database"] = "unavailable"
        status["status"] = "degraded"

    if status["status"] == "degraded": response.status_code = 503

    return status
