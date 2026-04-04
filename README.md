# URL Shortener API

> High-performance URL shortener with analytics, rate limiting, and admin controls.  
> Built by **Anas Khan** ([@madriLysh](https://github.com/madriLysh))

![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white)
![Scalar](https://img.shields.io/badge/Docs-Scalar-black)

---

## Features

- Fast redirects with Redis caching
- Click analytics — referrers, countries, browsers, time-series
- Rate limiting per endpoint via Redis Lua scripts
- URL expiration with background auto-cleanup scheduler
- Admin controls — delete, restore, bulk cleanup
- Search URLs by long URL
- Top URLs leaderboard
- Edit tokens for secure URL updates
- Distributed locks for safe concurrent operations

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   FastAPI   │────▶│    Redis    │
│             │◀────│   Routes    │◀────│    Cache    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  URLService │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  PostgreSQL │
                    │ (SQLAlchemy)│
                    └─────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16
- Redis

### 1. Clone & Install

```bash
git clone https://github.com/madriLysh/url-shortener.git
cd url-shortener
pip install -r requirements.txt
```

### 2. Create the Database

```bash
createdb url_shortener_db
python3 init_db.py
```

### 3. Configure Environment

Create a `.env` file or export variables:

```bash
export DATABASE_URL="postgresql://localhost/url_shortener_db"
export REDIS_HOST="localhost"
export REDIS_PORT="6379"
export ADMIN_API_KEY="your-secret-key"
export BASE_URL="http://localhost:8000"
```

### 4. Run

```bash
python3 main.py
```

Visit **http://localhost:8000/scalar** for interactive API documentation.

---

## API Endpoints

### URL Management

| Method | Endpoint | Description | Rate Limit |
|--------|----------|-------------|------------|
| `POST` | `/shorten` | Create short URL | 10/min |
| `GET` | `/{short_code}` | Redirect to long URL | 1000/min |
| `PATCH` | `/urls/{short_code}` | Update long URL | 10/min |
| `GET` | `/urls/{short_code}/stats` | URL statistics | 100/min |
| `GET` | `/urls/{short_code}/analytics` | Detailed analytics | 100/min |
| `GET` | `/urls/{short_code}/history` | Click history | 100/min |
| `GET` | `/urls/recent` | Recently created URLs | 100/min |
| `GET` | `/urls/top` | Top performing URLs | 100/min |
| `GET` | `/urls/search` | Find by long URL | 100/min |

### Admin Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `DELETE` | `/admin/urls/{short_code}` | Delete URL | `X-API-Key` |
| `POST` | `/admin/urls/{short_code}/restore` | Restore deleted URL | `X-API-Key` |
| `POST` | `/admin/urls/cleanup` | Bulk delete expired URLs | `X-API-Key` |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (DB + Redis) |

---

## Request Examples

### Create Short URL

```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{
    "long_url": "https://example.com",
    "custom_alias": "mylink",
    "expires_at": "2027-01-01T00:00:00"
  }'
```

**Response:**
```json
{
  "short_code": "mylink",
  "short_url": "http://localhost:8000/mylink",
  "long_url": "https://example.com",
  "edit_token": "abc123xyz"
}
```

### Update a URL

```bash
curl -X PATCH http://localhost:8000/urls/mylink \
  -H "Content-Type: application/json" \
  -d '{
    "new_url": "https://updated.com",
    "edit_token": "abc123xyz"
  }'
```

### Get Analytics

```bash
curl "http://localhost:8000/urls/mylink/analytics?period=7d"
```

**Response:**
```json
{
  "clicks_per_day": [
    {"date": "2026-04-03", "count": 150},
    {"date": "2026-04-02", "count": 89}
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

### Admin Delete

```bash
curl -X DELETE http://localhost:8000/admin/urls/mylink \
  -H "X-API-Key: your-secret-key"
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Base URL for generated short links |
| `DATABASE_URL` | `postgresql://localhost/url_shortener_db` | PostgreSQL connection string |
| `REDIS_HOST` | `localhost` | Redis server host |
| `REDIS_PORT` | `6379` | Redis server port |
| `ADMIN_API_KEY` | *(required)* | Admin API authentication key |
| `RATE_LIMIT_REQUESTS` | `10` | Create URL rate limit (per 60s) |
| `RATE_LIMIT_READS` | `100` | Read endpoint rate limit (per 60s) |
| `RATE_LIMIT_WRITES` | `10` | Write endpoint rate limit (per 60s) |
| `RATE_LIMIT_REDIRECTS` | `1000` | Redirect rate limit (per 60s) |
| `CACHE_TTL` | `3600` | Redis cache duration (seconds) |
| `DEFAULT_TTL` | `3600` | Default URL expiration (seconds) |
| `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size |
| `SYNC_INTERVAL` | `60` | Background sync interval (seconds) |
| `EXPIRY_CLEANUP_INTERVAL` | `3600` | Expired URL cleanup interval (seconds) |

---

## Period Filters

Analytics, history, and top URL endpoints support time filtering via `?period=`:

| Period | Description |
|--------|-------------|
| `1d` | Last 24 hours |
| `1w` | Last 7 days |
| `1m` | Last 30 days |
| `3m` | Last 90 days |
| `1y` | Last 365 days |

Example: `GET /urls/abc123/analytics?period=1w`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | [FastAPI](https://fastapi.tiangolo.com/) |
| ORM | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) |
| Database | [PostgreSQL 16](https://www.postgresql.org/) |
| Cache / Rate Limiting | [Redis](https://redis.io/) |
| Validation | [Pydantic v2](https://docs.pydantic.dev/) |
| API Docs | [Scalar](https://scalar.com/) |
| Server | [Uvicorn](https://www.uvicorn.org/) |

---

## Project Structure

```
url_shortener/
├── api/
│   ├── admin.py          # Admin routes
│   ├── dependencies.py   # DI: DB, Redis, rate limiting, auth
│   ├── health.py         # Health check route
│   ├── routes.py         # URL routes
│   └── schemas.py        # Pydantic models
├── infrastructure/
│   ├── database.py       # SQLAlchemy engine & session
│   └── redis_client.py   # Redis client with Lua scripts
├── services/
│   └── url_service.py    # Business logic
├── config.py             # Environment config
├── log.py                # Logger setup
├── main.py               # App entrypoint
├── scheduler.py          # Background jobs
└── init_db.py            # Table creation script
```

---

## Author

**Anas Khan**  
GitHub: [@madriLysh](https://github.com/madriLysh)
