# URL Shortener — Project Notes

This file is a living reference for the codebase: architecture, known pitfalls, and the bug-fix history. Update it when you change behavior that future maintainers (or agents) should know about.

---

## Stack

- **Framework:** FastAPI + Uvicorn
- **ORM:** SQLAlchemy 2.0
- **Database:** PostgreSQL 16 (production), SQLite acceptable for unit tests
- **Cache / Rate Limiting:** Redis 7 with Lua scripts
- **Docs:** Scalar
- **Background jobs:** APScheduler

---

## Architecture

```
Client → FastAPI routes → URLService → PostgreSQL
                          ↓
                        Redis (cache, counters, rate limits, referrers)
```

Key components:

- `api/routes.py` — public URL endpoints (`/shorten`, `/{code}`, stats, analytics, etc.)
- `api/admin.py` — admin endpoints (delete, restore, cleanup)
- `api/dependencies.py` — DI, rate-limit helpers, period calculation
- `services/url_service.py` — business logic and Redis/DB coordination
- `models/url_models.py` — SQLAlchemy models
- `infrastructure/redis_client.py` — Redis wrapper with Lua scripts
- `scheduler.py` — background sync of click counts and expired-URL cleanup

---

## Important behavioral details

### Short-code uniqueness

The `urls.short_code` column no longer has a global `unique=True` constraint. Instead, there is a **partial unique index** that only enforces uniqueness among **active** rows:

```python
Index(
    "ix_urls_short_code_active_unique",
    "short_code",
    unique=True,
    postgresql_where=is_active.is_(True),
    sqlite_where=is_active.is_(True),
)
```

This makes `ALLOW_REUSE_DELETED_CODES=true` actually work: a deleted code can be recreated because the old inactive row no longer blocks it at the database level.

### Custom-code collision checks

`_code_exist(code, is_active=None)` checks for a code in any state. In `create_url`:

- `ALLOW_REUSE_DELETED_CODES=true` → only active rows block reuse.
- `ALLOW_REUSE_DELETED_CODES=false` → any row (active or deleted) blocks reuse.

As a backstop, `create_url` wraps `commit()` in a `try/except IntegrityError` that rolls back and raises `ValueError` → 400.

### Timezones

All datetime columns are now `DateTime(timezone=True)`:

- `URL.created_at`
- `URL.expires_at`
- `Click.clicked_at`
- `ReferrerState.last_clicked`

Production uses PostgreSQL; tests use an in-memory SQLite database.

### Click recording

`record_click` commits the `Click` row in its own transaction first, then runs `_upsert_referrer` in a separate transaction. Referrer analytics failures cannot lose the click or poison the session.

### SSRF guard

`_is_valid_long_url` is called at the top of `create_url`. It blocks:

- Non-HTTP/HTTPS schemes
- Blocked hostnames (`localhost`, `metadata.google.internal`)
- Literal private/loopback/link-local IPs (e.g., `127.0.0.1`, `10.0.0.5`, `169.254.169.254`, `[::1]`)

It does **not** resolve domains, so DNS-rebinding domains that point to private IPs are not blocked.

### Redis sorted-set helper

`RedisClient.zrevrange(key, start, end, scores=False)` takes raw Redis indices. Callers compute the range themselves (`offset` to `offset + limit - 1`).

### SQLite test compatibility

`Click.id` is declared as `BigInteger().with_variant(Integer, "sqlite")` so SQLite's autoincrement works in tests while PostgreSQL keeps `BIGINT`.

---

## Bug-fix history

### Batch 1 — from `fix.txt`

1. **Custom-code collision logic** — state-agnostic `_code_exist`, partial unique index, `IntegrityError` backstop.
2. **SSRF guard wired in** — `_is_valid_long_url` called at start of `create_url`.
3. **Timezone crash in `extend_url_expiry`** — made datetime columns timezone-aware.
4. **`record_click` dead session** — split into two independent transactions.
5. **`sync_clicks_to_db` error accounting** — `None` returned on real batch failures only.

### Batch 2 — from updated `fix.txt`

6. **FakeRedis `zincrby` signature** — aligned with real `RedisClient.zincrby(key, member, increment=1)`.
7. **`is_custom` flag** — `create_url` now sets `is_custom=bool(custom_code)`.
8. **Missing FakeRedis methods** — added `increment_hash_field`, `pfadd`, `pfcount`, and `zrevrange` so `increment_clicks` and `get_recent_urls` are testable.

### Additional bugs found during review

9. **`get_click_history` parameter order** — fixed swapped `offset`/`limit` arguments.
10. **Recent-URLs pagination** — fixed double `offset + limit - 1` computation in `RedisClient.zrevrange`.

---

## Running tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

Current result: **82 passed**.

---

## Gaps / future work

- No Alembic migrations yet. Schema changes require `drop/recreate` via `init_db.py` for existing databases.
- Rate limiting reads `service.redis` (mutable attribute reach-through) instead of declaring its own `Depends(get_redis_client)`. All routes call `check_rate_limit_*(service.redis, ...)`. Refactor candidate: make `check_rate_limit_create/read/write/redirect` take redis via `Depends` directly. Related: `get_redis_client` 500-vs-degraded issue.
- Remaining unit-test coverage gaps (noted in `fix.txt`):
  - `get_url` scenarios (cache hit, deleted invalidation, expired-in-cache, cache miss + DB backfill, expired-in-DB deactivation, total miss)
  - `increment_clicks`
  - `update_url`
  - `restore_url`
