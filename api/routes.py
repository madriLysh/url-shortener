from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from api.dependencies import (
    check_rate_limit_create,
    check_rate_limit_read,
    check_rate_limit_redirect,
    check_rate_limit_write,
    get_client_ip,
    get_url_service,
    since_calculation,
)
from api.schemas import (
    TopURLsResponse,
    URLAnalytics,
    URLClickHistoryResponse,
    URLCreate,
    URLResponse,
    URLStats,
    URLUpdate,
)
from config import Config
from services import URLService

router = APIRouter()

@router.post("/shorten", response_model=URLResponse, status_code=status.HTTP_201_CREATED)
def create_short_url(
    data: URLCreate,
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip),
):
    check_rate_limit_create(
        service.redis,
        client_ip
    )

    try:
        short_code, edit_token = service.create_url(
            long_url=str(data.long_url),
            creator_ip=client_ip,
            expires_at=data.expires_at,
            custom_code=data.custom_alias,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {
        "short_code": short_code,
        "edit_token": edit_token,
        "short_url": f"{Config.BASE_URL}/{short_code}",
        "long_url": str(data.long_url),
    }

@router.get("/urls/{short_code}/stats", response_model=URLStats)
def get_stats(
    short_code: str,
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)):

    check_rate_limit_read(
        service.redis,
        "get_stats",
        client_ip
    )

    stats = service.get_url_stats(short_code)
    if not stats:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return stats

@router.get("/urls/recent")
def list_recent(
    page : int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size : int = Query(Config.DEFAULT_PAGE_SIZE,
                            ge=1,
                            le=Config.MAX_PAGE_SIZE,
                            description="Items per page"),
    service : URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_read(
        service.redis,
        "list_recent",
        client_ip
    )

    offset = (page - 1) * page_size
    urls = service.get_recent_urls(offset= offset, limit=page_size)

    active_urls = []
    for url in urls:
        data = service.get_url(url)
        if data:
            active_urls.append(
                {
                    "short_code": url,
                    "short_url": f"{Config.BASE_URL}/{url}",
                    "long_url": data["long_url"]
                }
            )
    return {
        "items": active_urls,
        "page": page,
        "page_size": page_size,
        "count": len(active_urls)
    }

@router.get("/{short_code}")
def redirect_to_url(
    short_code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_redirect(
        service.redis,
        client_ip
    )

    url_data = service.get_url(short_code)

    if not url_data:
        if service.url_ever_existed(short_code):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="URL has expired.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found.")

    agent = request.headers.get("user-agent")
    referrer = request.headers.get("referer")
    url_id = url_data["id"]

    background_tasks.add_task(service.increment_clicks, short_code, client_ip)
    background_tasks.add_task(service.record_click, url_id, client_ip, agent, referrer)

    return RedirectResponse(url=url_data["long_url"], status_code=status.HTTP_302_FOUND)

@router.patch("/urls/{short_code}")
def update_url(
    short_code: str,
    data : URLUpdate,
    service : URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_write(
        service.redis,
        "update_url",
        client_ip
    )

    try:
        service.update_url(short_code, str(data.new_url), data.edit_token)
        return {"detail": "URL updated"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/urls/{short_code}/history", response_model=URLClickHistoryResponse)
def get_click_history(
    short_code: str,
    period: Optional[str] = Query(None, description="1d, 1w, 1m, 3m, 1y"),
    page : int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size : int = Query(Config.DEFAULT_PAGE_SIZE,
                            ge=1,
                            le=Config.MAX_PAGE_SIZE,
                            description="Items per page"),
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_read(
        service.redis,
        "get_history",
        client_ip
    )

    offset = (page - 1) * page_size

    since = since_calculation(period)

    history = service.get_url_history(short_code, since, page_size, offset)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return {
        "short_code": history["short_code"],
        "long_url": history["long_url"],
        "items": history["clicks"],
        "page": page,
        "page_size": page_size,
        "count": len(history["clicks"])
    }

@router.get("/urls/top", response_model=TopURLsResponse)
def get_top_urls(
    limit: int = Query(10, ge=1, le=100),
    period: Optional[str] = Query(None, description="1d, 1w, 1m, 3m, 1y"),
    page : int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size : int = Query(Config.DEFAULT_PAGE_SIZE,
                            ge=1,
                            le=Config.MAX_PAGE_SIZE,
                            description="Items per page"),
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_read(
        service.redis,
        "top_url",
        client_ip
    )

    offset = (page - 1) * page_size

    since = since_calculation(period)
    top_urls = service.get_top_urls(since, offset, limit)
    return {
        "items": top_urls,
        "page": page,
        "page_size": page_size,
        "count": len(top_urls)
    }

@router.get("/urls/{short_code}/analytics", response_model=URLAnalytics)
def get_url_analytics(
    short_code: str,
    period: Optional[str] = Query(None, description="1d, 1w, 1m, 3m, 1y"),
    service: URLService = Depends(get_url_service),
    client_ip : str = Depends(get_client_ip)
):
    check_rate_limit_read(
        service.redis,
        "analytics",
        client_ip
    )

    since = since_calculation(period)

    analytics = service.get_url_analytics(short_code, since)
    if analytics is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return analytics

@router.get("/urls/search")
def search_by_long_url(
    long_url: str = Query(..., description="The long URL to search for"),
    service: URLService = Depends(get_url_service),
    client_ip: str = Depends(get_client_ip)
):
    check_rate_limit_read(service.redis, "search", client_ip)
    results = service.search_by_long_url(long_url)
    if not results:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return results
