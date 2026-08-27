from fastapi.testclient import TestClient
from fastapi import status
from main import build_application
from api.dependencies import get_redis_client
from infrastructure import get_db
import pytest

class FakeWorkingDB:
    def execute(self, query): return None
class FakeDeadDB:
    def execute(self, query): raise Exception("connection refused")

class FakePingOk:
    def ping(self): return True
class FakeWorkingRedis:
    def __init__(self) -> None:
        self.client = FakePingOk()

class FakePingDead:
    def ping(self) : raise Exception("connection refused")
class FakeDeadRedis:
    def __init__(self) -> None:
        self.client = FakePingDead()

@pytest.mark.parametrize("db, cache, state, status_code", [
    (FakeWorkingDB(), FakeWorkingRedis(), {"status": "ok", "redis": "ok", "database": "ok"}, status.HTTP_200_OK),
    (FakeWorkingDB(), FakeDeadRedis(), {"status": "degraded", "redis": "unavailable", "database": "ok"}, status.HTTP_503_SERVICE_UNAVAILABLE),
    (FakeDeadDB(), FakeWorkingRedis(), {"status": "degraded", "redis": "ok", "database": "unavailable"}, status.HTTP_503_SERVICE_UNAVAILABLE),
    (FakeDeadDB(), FakeDeadRedis(), {"status": "degraded", "redis": "unavailable", "database": "unavailable"}, status.HTTP_503_SERVICE_UNAVAILABLE)
])
def test_health(db, cache, state, status_code):
    app = build_application()
    app.dependency_overrides[get_db] = lambda : db
    app.dependency_overrides[get_redis_client] = lambda : cache

    response = TestClient(app).get("/health")
    assert response.status_code == status_code
    assert response.json() == state
    app.dependency_overrides.clear()