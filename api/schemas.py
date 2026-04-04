from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, HttpUrl


class URLCreate(BaseModel):
    long_url: HttpUrl
    custom_alias: Optional[str] = None
    expires_at: Optional[datetime] = None

class URLUpdate(BaseModel):
    new_url: HttpUrl
    edit_token: str

class URLResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str

class ReferrerStat(BaseModel):
    domain: str
    click_count: int

class URLStats(BaseModel):
    click_count: int
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    top_referrers: Optional[list[ReferrerStat]] = None
    unique_visitors: int = 0

class ErrorResponse(BaseModel):
    detail: str
    short_url: Optional[str] = None
    long_url: Optional[str] = None

class URLClickHistory(BaseModel):
    clicked_at: datetime = datetime.now(timezone.utc)
    user_agent: Optional[str] = None
    referrer: Optional[str] = None
    country_code: Optional[str] = None

class URLClickHistoryResponse(BaseModel):
    short_code: str
    long_url: str
    items: list[URLClickHistory]
    page: int
    page_size: int
    count: int

class URLDeleteResponse(BaseModel):
    deleted_count: int


class ClickPerDay(BaseModel):
    date: str
    count: int

class CountryStat(BaseModel):
    country_code: Optional[str]
    count: int

class BrowserStat(BaseModel):
    browser: str
    count: int

class URLAnalytics(BaseModel):
    clicks_per_day: list[ClickPerDay]
    top_countries: list[CountryStat]
    top_browsers: list[BrowserStat]

class TopURLItem(BaseModel):
    short_code: str
    long_url: str
    click_count: int
    short_url: str

class TopURLsResponse(BaseModel):
    items: list[TopURLItem]
    page: int
    page_size: int
    count: int
