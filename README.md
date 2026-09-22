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

| Name | Purpose | Default |
|------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://localhost/url_shortener_db` |
| `REDIS_HOST` | Redis host | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `ADMIN_API_KEY` | Key required for `/admin/*` endpoints (header `X-API-Key`) | *(required)* |
| `BASE_URL` | Base URL used in generated short links | `http://localhost:8000` |
| `RATE_LIMIT_REQUESTS` | Create-URL limit per 60s window | `10` |
| `RATE_LIMIT_REDIRECTS` | Redirect limit per 60s window | `1000` |

## API overview

| Method | Endpoint | Description | Auth required |
|--------|----------|-------------|---------------|
| `POST` | `/shorten` | Create a short URL (optional custom alias, expiry) | No |
| `GET` | `/{short_code}` | Redirect to the long URL | No |
| `PATCH` | `/urls/{short_code}` | Update the long URL (requires edit token) | No |
| `GET` | `/urls/{short_code}/stats` | Basic URL statistics | No |
| `GET` | `/urls/{short_code}/analytics` | Analytics (clicks per day, countries, browsers, referrers) | No |
| `GET` | `/urls/{short_code}/history` | Click history | No |
| `GET` | `/urls/recent` | Recently created URLs | No |
| `GET` | `/urls/top` | Top URLs by click count | No |
| `GET` | `/urls/search` | Find a short URL by long URL | No |
| `GET` | `/health` | Health check (DB + Redis) | No |
| `DELETE` | `/admin/urls/{short_code}` | Delete a URL | `X-API-Key` |
| `POST` | `/admin/urls/{short_code}/restore` | Restore a deleted URL | `X-API-Key` |
| `POST` | `/admin/urls/cleanup` | Bulk-delete expired URLs | `X-API-Key` |

Full interactive documentation is available at `/scalar` on a running instance.

## Testing & CI

Run the test suite locally (requires PostgreSQL and Redis; the compose `test` profile provides both):

```bash
pytest
```

The pipeline in `.github/workflows/test.yml` runs on every push and PR to `main`:

1. `ruff check .` — lint gate.
2. `pytest` against PostgreSQL 16 and Redis 7 service containers; on failure the JUnit XML report is uploaded as a `pytest-report` artifact.
3. On pushes to `main` only: multi-stage Docker build, pushed to `ghcr.io/madrilysh/url-shortener` as `latest` and a short-SHA tag.

## License

MIT. See `LICENSE.txt`.
