# url-shortener

A URL shortener API built with FastAPI, PostgreSQL, and Redis.

![Test](https://github.com/madriLysh/url-shortener/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## What it is

A production-grade URL shortener API built with FastAPI, PostgreSQL, and Redis, featuring analytics, rate limiting, and admin controls.

## Features

- Shorten and redirect
- Custom aliases
- Click analytics (referrer, country, user-agent)
- Link expiration with background cleanup
- Redis-backed rate limiting via Lua scripts (atomic, race-free)
- Distributed locks for alias collision handling
- Edit tokens for secure URL updates
- Search URLs by long URL
- Top URLs leaderboard
- Admin endpoints (delete / restore / cleanup)

## Architecture

Request flow: client -> FastAPI -> Redis (rate limit / cache) -> PostgreSQL.

- Rate limiting runs as Lua scripts inside Redis, so the check-and-increment is a single atomic operation. No two concurrent requests can both slip under the limit.
- Custom-alias creation is guarded by a Redis distributed lock, so two concurrent requests for the same alias cannot both reserve it.
- Redis and PostgreSQL both use connection pools (configured via `REDIS_MAX_CONNECTIONS` and `DB_POOL_SIZE`), avoiding per-request connection setup.
- The Dockerfile is multi-stage: dependencies are built once, the final image is `python:3.12-slim` running as a non-root user.

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI / Python 3.12 |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 |
| Cache | Redis 7 |
| Testing | pytest (213 tests) |
| CI/CD | GitHub Actions -> ghcr.io |

## Quick start

### (a) Docker

```bash
docker pull ghcr.io/madrilysh/url-shortener:latest
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:password@host.docker.internal:5432/url_shortener_db \
  -e REDIS_HOST=host.docker.internal \
  -e ADMIN_API_KEY=your-secret-key \
  ghcr.io/madrilysh/url-shortener:latest
```

### (b) Local development

```bash
git clone https://github.com/madriLysh/url-shortener.git
cd url-shortener
pip install -r requirements.txt

# Start PostgreSQL and Redis
DB_USER=postgres DB_PASSWORD=postgres DB_NAME=url_shortener_db docker compose up -d db cache

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/url_shortener_db
export ADMIN_API_KEY=your-secret-key

uvicorn --factory main:build_application --reload
```

Interactive API docs are served at `http://localhost:8000/scalar`.

### Environment variables

All variables are read in `config.py`.

| Name | Purpose | Default |
|------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://localhost/url_shortener_db` |
| `REDIS_HOST` | Redis host | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `ADMIN_API_KEY` | Key for `/admin/*` endpoints (header `X-API-Key`) | *(required)* |
| `BASE_URL` | Base URL used in generated short links | `http://localhost:8000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins | `*` |
| `MAX_CODE_GENERATION_ATTEMPTS` | Retries when generating a unique short code | `5` |
| `MIN_CUSTOM_CODE_LENGTH` | Minimum custom alias length | `3` |
| `MAX_CUSTOM_CODE_LENGTH` | Maximum custom alias length | `20` |
| `ALLOW_REUSE_DELETED_CODES` | Allow reusing codes of deleted URLs | `false` |
| `DEFAULT_TTL` | Default URL expiration (seconds) | `3600` |
| `CACHE_TTL` | Redis cache TTL (seconds) | `3600` |
| `DEFAULT_PAGE_SIZE` | Default pagination page size | `10` |
| `MAX_PAGE_SIZE` | Maximum pagination page size | `100` |
| `DB_POOL_SIZE` | SQLAlchemy connection pool size | `10` |
| `DB_MAX_OVERFLOW` | Extra connections beyond the pool size | `10` |
| `DB_POOL_TIMEOUT` | Seconds to wait for a pooled connection | `30` |
| `DB_ECHO` | Log all SQL statements | `false` |
| `EXPIRED_URLS_BATCH_SIZE` | Rows per expired-URL cleanup batch | `1000` |
| `REDIS_MAX_CONNECTIONS` | Redis connection pool size | `50` |
| `REDIS_SOCKET_TIMEOUT` | Redis socket timeout (seconds) | `5` |
| `REDIS_CONNECT_TIMEOUT` | Redis connect timeout (seconds) | `5` |
| `REDIS_HEALTH_CHECK_INTERVAL` | Redis pool health-check interval (seconds) | `30` |
| `RECENT_URLS_LIMIT` | Maximum entries in the recent-URLs list | `100` |
| `TOP_REFERRERS_LIMIT` | Maximum rows in top-referrers analytics | `10` |
| `RATE_LIMIT_REQUESTS` | Create-URL limit per window | `10` |
| `RATE_LIMIT_WINDOW` | Rate-limit window (seconds) | `60` |
| `RATE_LIMIT_REDIRECTS` | Redirect limit per window | `1000` |
| `RATE_LIMIT_READS` | Read-endpoint limit per window | `100` |
| `RATE_LIMIT_WRITES` | Write-endpoint limit per window | `10` |
| `SYNC_INTERVAL` | Click-count sync interval (seconds) | `60` |
| `BATCH_SIZE` | Rows per click-sync batch | `1000` |
| `EXPIRY_CLEANUP_INTERVAL` | Expired-URL cleanup interval (seconds) | `3600` |

## API overview

| Method | Endpoint | Description | Auth required | Rate limit |
|--------|----------|-------------|---------------|------------|
| `POST` | `/shorten` | Create a short URL (optional custom alias, expiry) | No | 10/min |
| `GET` | `/{short_code}` | Redirect to the long URL | No | 1000/min |
| `PATCH` | `/urls/{short_code}` | Update the long URL (requires edit token) | No | 10/min |
| `GET` | `/urls/{short_code}/stats` | Basic URL statistics | No | 100/min |
| `GET` | `/urls/{short_code}/analytics` | Analytics (clicks per day, countries, browsers, referrers) | No | 100/min |
| `GET` | `/urls/{short_code}/history` | Click history | No | 100/min |
| `GET` | `/urls/recent` | Recently created URLs | No | 100/min |
| `GET` | `/urls/top` | Top URLs by click count | No | 100/min |
| `GET` | `/urls/search` | Find a short URL by long URL | No | 100/min |
| `GET` | `/health` | Health check (DB + Redis) | No | — |
| `DELETE` | `/admin/urls/{short_code}` | Delete a URL | `X-API-Key` | — |
| `POST` | `/admin/urls/{short_code}/restore` | Restore a deleted URL | `X-API-Key` | — |
| `POST` | `/admin/urls/cleanup` | Bulk-delete expired URLs | `X-API-Key` | — |

Limits are per client IP over a 60-second window (`RATE_LIMIT_WINDOW`); defaults shown. Full interactive documentation is available at `/scalar` on a running instance.

## Request examples

### Create a short URL

```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{
    "long_url": "https://example.com/some/long/page",
    "custom_alias": "mylink",
    "expires_at": "2027-01-01T00:00:00"
  }'
```

```json
{
  "short_code": "mylink",
  "edit_token": "a1b2c3d4e5f6",
  "short_url": "http://localhost:8000/mylink",
  "long_url": "https://example.com/some/long/page"
}
```

### Update a URL

```bash
curl -X PATCH http://localhost:8000/urls/mylink \
  -H "Content-Type: application/json" \
  -d '{
    "new_url": "https://example.com/updated",
    "edit_token": "a1b2c3d4e5f6"
  }'
```

```json
{
  "detail": "URL updated"
}
```

### Get analytics

```bash
curl "http://localhost:8000/urls/mylink/analytics?period=1w"
```

```json
{
  "clicks_per_day": [
    {"date": "2026-09-22", "count": 150},
    {"date": "2026-09-21", "count": 89}
  ],
  "top_countries": [
    {"country_code": "US", "count": 120},
    {"country_code": "GB", "count": 45}
  ],
  "top_browsers": [
    {"browser": "Chrome", "count": 180},
    {"browser": "Firefox", "count": 59}
  ]
}
```

## Period filters

The analytics, history, and top-URLs endpoints accept an optional `?period=` query parameter:

| Period | Time range |
|--------|------------|
| `1d` | Last 24 hours |
| `1w` | Last 7 days |
| `1m` | Last 30 days |
| `3m` | Last 90 days |
| `1y` | Last 365 days |

An omitted or unrecognized value disables time filtering.

## Testing & CI

Run the test suite locally (requires PostgreSQL and Redis; the compose `test` profile provides both):

```bash
pytest
```

The pipeline in `.github/workflows/test.yml` runs on every push and PR to `main`:

1. `ruff check .` — lint gate.
2. `pytest` against PostgreSQL 16 and Redis 7 service containers; on failure the JUnit XML report is uploaded as a `pytest-report` artifact.
3. On pushes to `main` only: multi-stage Docker build, pushed to `ghcr.io/madrilysh/url-shortener` as `latest` and a short-SHA tag.

## Project structure

```
url-shortener/
├── api/
│   ├── admin.py          # Admin routes (delete / restore / cleanup)
│   ├── dependencies.py   # DI: DB, Redis, rate limiting, auth
│   ├── health.py         # Health check
│   ├── routes.py         # URL routes
│   └── schemas.py        # Pydantic models
├── infrastructure/
│   ├── database.py       # SQLAlchemy engine and session
│   └── redis_client.py   # Redis client, Lua scripts, locks
├── models/
│   └── url_models.py     # ORM models (URL, Click, ReferrerState)
├── services/
│   └── url_service.py    # Business logic
├── tests/                # pytest suite (unit + integration)
├── utils/
│   └── base62.py         # Base62 short-code generation
├── config.py             # Environment configuration
├── main.py               # App factory and entrypoint
├── scheduler.py          # Background jobs (click sync, expiry cleanup)
├── init_db.py            # Table creation script
└── log.py                # Logger setup
```

## License

MIT. See `LICENSE.txt`.

## Author

**Anas Khan** — GitHub: [@madriLysh](https://github.com/madriLysh)
