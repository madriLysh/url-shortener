from os import getenv


class Config:
    BASE_URL: str = getenv("BASE_URL", "http://localhost:8000")
    LOG_LEVEL: str = getenv("LOG_LEVEL", "INFO")
    ADMIN_API_KEY: str = getenv("ADMIN_API_KEY", "")

    MAX_CODE_GENERATION_ATTEMPTS: int = int(getenv("MAX_CODE_GENERATION_ATTEMPTS", "5"))

    MIN_CUSTOM_CODE_LENGTH: int = int(getenv("MIN_CUSTOM_CODE_LENGTH", "3"))
    MAX_CUSTOM_CODE_LENGTH: int = int(getenv("MAX_CUSTOM_CODE_LENGTH", "20"))

    ALLOW_REUSE_DELETED_CODES: bool = getenv("ALLOW_REUSE_DELETED_CODES", "false").lower() == "true"

    DEFAULT_TTL: int = int(getenv("DEFAULT_TTL", "3600"))
    CACHE_TTL: int = int(getenv("CACHE_TTL", "3600"))

    DEFAULT_PAGE_SIZE: int = int(getenv("DEFAULT_PAGE_SIZE", "10"))
    MAX_PAGE_SIZE: int = int(getenv("MAX_PAGE_SIZE", "100"))

    DATABASE_URL: str = getenv("DATABASE_URL", "postgresql://localhost/url_shortener_db")
    DB_POOL_SIZE: int = int(getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT: int = int(getenv("DB_POOL_TIMEOUT", "30"))
    DB_ECHO: bool = getenv("DB_ECHO", "false").lower() == "true"
    EXPIRED_URLS_BATCH_SIZE: int = int(getenv("EXPIRED_URLS_BATCH_SIZE", "1000"))

    REDIS_HOST: str = getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(getenv("REDIS_PORT", "6379"))
    REDIS_MAX_CONNECTIONS: int = int(getenv("REDIS_MAX_CONNECTIONS", "50"))
    REDIS_SOCKET_TIMEOUT: int = int(getenv("REDIS_SOCKET_TIMEOUT", "5"))
    REDIS_CONNECT_TIMEOUT: int = int(getenv("REDIS_CONNECT_TIMEOUT", "5"))
    REDIS_HEALTH_CHECK_INTERVAL: int = int(getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))

    RECENT_URLS_LIMIT: int = int(getenv("RECENT_URLS_LIMIT", "100"))
    TOP_REFERRERS_LIMIT: int = int(getenv("TOP_REFERRERS_LIMIT", "10"))

    RATE_LIMIT_REQUESTS: int = int(getenv("RATE_LIMIT_REQUESTS", "10"))
    RATE_LIMIT_WINDOW: int = int(getenv("RATE_LIMIT_WINDOW", "60"))
    RATE_LIMIT_REDIRECTS: int = int(getenv("RATE_LIMIT_REDIRECTS", "1000"))
    RATE_LIMIT_READS: int = int(getenv("RATE_LIMIT_READS", "100"))
    RATE_LIMIT_WRITES: int = int(getenv("RATE_LIMIT_WRITES", "10"))

    SYNC_INTERVAL: int = int(getenv("SYNC_INTERVAL", "60"))
    BATCH_SIZE: int = int(getenv("BATCH_SIZE", "1000"))
    EXPIRY_CLEANUP_INTERVAL: int = int(getenv("EXPIRY_CLEANUP_INTERVAL", "3600"))

    CORS_ORIGINS: list = getenv("CORS_ORIGINS", "*").split(",")


config = Config()
