"""All tunables live here and can be overridden with environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rushline:rushline@localhost:5432/rushline"
    redis_url: str = "redis://localhost:6379/0"
    db_pool_size: int = 20

    hmac_secret: str = "dev-secret-change-me"

    reservation_ttl_seconds: int = 120      # how long a buyer holds a reservation
    admission_rate_per_second: float = 50   # waiting room throughput
    admission_ttl_seconds: int = 120        # how long an admission token stays valid

    rate_limit_max: int = 30                # requests per buyer ...
    rate_limit_window_seconds: float = 10   # ... per sliding window

    payment_min_ms: int = 200
    payment_max_ms: int = 800
    payment_failure_rate: float = 0.05

    # Artificial "business logic" delay inside the naive checkout (0 = none).
    naive_think_ms: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
