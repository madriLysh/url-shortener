from time import sleep, time
from typing import Optional, cast

from redis import ConnectionError as RedisConnectionError
from redis import ConnectionPool, Redis, RedisError
from typing_extensions import Self

from config import Config
from log import get_logger

logger = get_logger(__name__)

class RedisConnectionPool:
    _instance: Optional['RedisConnectionPool'] = None
    _pool: Optional[ConnectionPool] = None

    def __new__(cls) -> 'RedisConnectionPool':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _create_pool(self) -> ConnectionPool:
        return ConnectionPool(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=0,
            decode_responses=True,
            socket_connect_timeout=Config.REDIS_CONNECT_TIMEOUT,
            socket_timeout=Config.REDIS_SOCKET_TIMEOUT,
            max_connections=Config.REDIS_MAX_CONNECTIONS,
            retry_on_timeout=True,
            health_check_interval=Config.REDIS_HEALTH_CHECK_INTERVAL,
            socket_keepalive=True
        )

    def get_connection(self) -> Optional[Redis]:
        if self._pool is None:
            self._pool = self._create_pool()

        try:
            client = Redis(connection_pool=self._pool)
            client.ping()
            return client
        except RedisConnectionError:
            self._pool = None
            return None

class RedisClient:

    def __init__(self, client: Redis):
        self.client: Redis = client

    @classmethod
    def from_pool(cls) -> Self:
        pool = RedisConnectionPool()
        client = pool.get_connection()

        if client is None:
            raise RedisConnectionError("Unable to connect to Redis")
        return cls(client)

    # ========== Private Helper ==========

    def _execute(self, operation: str, *args, **kwargs):
        """Execute Redis operation with centralized error handling."""
        try:
            method = getattr(self.client, operation)
            return method(*args, **kwargs)
        except RedisError as e:
            logger.error(f"Redis error during '{operation}': {e}", exc_info=True)
            return None

    # ========== Basic Operations ==========

    def get(self, key: str) -> Optional[str]:
        result = self._execute("get", key)
        return str(result) if result is not None else None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        return self._execute("set", key, value, ex=ttl) is not None

    def delete(self, key: str) -> bool:
        return self._execute("unlink", key) is not None

    # ========== Hash Operations ==========

    def set_hash(self, key: str, data: dict[str, str], ttl: Optional[int] = None) -> bool:
        try:
            pipe = self.client.pipeline()
            pipe.hset(key, mapping=cast(dict, data))
            if ttl:
                pipe.expire(key, ttl)
            pipe.execute()
            return True
        except RedisError as e:
            logger.error(f"Failed to set hash for key '{key}': {e}", exc_info=True)
            return False

    def get_hash(self, key: str) -> Optional[dict[str, str]]:
        result = self._execute("hgetall", key)
        return result if result else None

    def increment_hash_field(self, key: str, field: str, amount: int = 1) -> bool:
        return self._execute("hincrby", key, field, amount) is not None

    def update_hash_field(self, key: str, field: str, value: str) -> bool:
        return self._execute("hset", key, field, value) is not None

    # ========== Pattern Operations ==========

    def delete_pattern(self, pattern: str) -> bool:
        try:
            keys = list(self.client.scan_iter(pattern))
            if keys:
                self.client.unlink(*keys)
            return True
        except RedisError as e:
            logger.error(f"Failed to delete pattern '{pattern}': {e}", exc_info=True)
            return False

    def scan_pattern(self, pattern: str) -> list[str]:
        try:
            return list(self.client.scan_iter(pattern))
        except RedisError as e:
            logger.error(f"Failed to scan pattern '{pattern}': {e}", exc_info=True)
            return []

    # ========== Distributed Locks ==========#

    @staticmethod
    def _lock_key(lock_name: str) -> str:
        return f"lock:{lock_name}"

    @staticmethod
    def _release_lock_lua() -> str:
        return """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        """

    def acquire_lock(
        self,
        lock_name: str,
        acquire_timeout: int = 10,
        lock_timeout: int = 10
    ) -> Optional[str]:
        from uuid import uuid4

        lock_key = self._lock_key(lock_name)
        token = str(uuid4())
        end_time = time() + acquire_timeout

        while time() < end_time:
            acquired = self._execute("set", lock_key, token, nx=True, ex=lock_timeout)
            if acquired:
                return token
            sleep(0.1)
        return None

    def release_lock(self, lock_name: str, token: str) -> bool:
        lock_key = self._lock_key(lock_name)
        result = self._execute("eval", self._release_lock_lua(), 1, lock_key, token)
        return result == 1

    @staticmethod
    def _extend_lock_lua() -> str:
        return """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                local ttl = redis.call("ttl", KEYS[1])
                if ttl > 0 then
                    return redis.call("expire", KEYS[1], ttl + tonumber(ARGV[2]))
                end
            end
            return 0
        """

    def extend_lock(self, lock_name: str, token: str, additional_time: int) -> bool:
        lock_key = self._lock_key(lock_name)
        result = self._execute("eval", self._extend_lock_lua(), 1, lock_key, token, additional_time)
        return result == 1

    # ========== Rate Limiting ==========

    @staticmethod
    def _rate_limit_lua() -> str:
        return """
            local count = redis.call("INCR", KEYS[1])
            if count == 1 then
                redis.call("EXPIRE", KEYS[1], ARGV[2])
            end
            if count > tonumber(ARGV[1]) then
                return {0, count}
            else
                return {1, count}
            end
        """

    def rate_limit(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        try:
            result = self.client.eval(
                self._rate_limit_lua(),
                1,
                key,
                max_requests,
                window_seconds
            )
            allowed = bool(result[0])
            count = int(result[1])
            return allowed, count
        except RedisError as e:
            logger.error(f"Rate limit check failed for key '{key}': {e}", exc_info=True)
            return True, 0

    # ========== Sorted Set Operations ==========

    @staticmethod
    def _zadd_and_trim_lua() -> str:
        return """
            redis.call("ZADD", KEYS[1], ARGV[1], ARGV[2])
            redis.call("ZREMRANGEBYRANK", KEYS[1], 0, -(tonumber(ARGV[3]) + 1))
        """

    def zadd_and_trim(
        self,
        key: str,
        member: str,
        score: float,
        limit: int,
    ) -> bool:
        try:
            self.client.eval(
                self._zadd_and_trim_lua(),
                1,
                key,
                score,
                member,
                limit,
            )
            return True
        except RedisError as e:
            logger.error(f"Failed to add and trim sorted set '{key}': {e}", exc_info=True)
            return False

    def zrevrange(
        self, key: str,
        offset: int = 0,
        limit: int = 10,
        scores: bool = False
    ) -> Optional[list]:
        result = self._execute("zrevrange", key, offset, offset + limit - 1, withscores=scores)
        return result if result else None

    def zincrby(self, key: str, member: str, increment: int = 1) -> bool:
        self._execute("zincrby", key, increment, member)
        return True

    def zrem(self, key: str, member: str) -> bool:
        return self._execute("zrem", key, member) is not None

    def zremrangebyrank(self, key: str, start: int, end: int) -> bool:
        return self._execute("zremrangebyrank", key, start, end) is not None

    def pipeline(self):
        return self.client.pipeline()

    def pfadd(self, key: str, value: str) -> bool:
        return  self._execute("pfadd", key, value) is not None

    def pfcount(self, key: str) -> int:
        result = self._execute("pfcount", key)
        return int(result) if result is not None else 0

    def expire_nx(self, key: str, ttl: int) -> bool:
        return self._execute("expire", key, ttl, "NX") is not None
