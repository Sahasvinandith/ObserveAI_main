"""
shared/redis_client.py

Redis connection factory with retry logic.
Reads REDIS_URL from the environment (default: redis://localhost:6379).
"""

import os
import time
import redis
from redis.exceptions import ConnectionError, RedisError


def get_redis_client(max_retries: int = 10, retry_delay: float = 2.0) -> redis.Redis:
    """
    Create and return a Redis client, retrying until the server is reachable.

    Args:
        max_retries: Maximum number of connection attempts before raising.
        retry_delay: Seconds to wait between attempts.

    Returns:
        A connected redis.Redis instance.

    Raises:
        ConnectionError: If the server is not reachable after max_retries attempts.
    """
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    for attempt in range(1, max_retries + 1):
        try:
            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            return client
        except (ConnectionError, RedisError, Exception) as exc:
            if attempt == max_retries:
                raise ConnectionError(
                    f"Cannot connect to Redis at {url} after {max_retries} attempts: {exc}"
                ) from exc
            time.sleep(retry_delay)

    # Unreachable, but satisfies type checkers
    raise ConnectionError(f"Cannot connect to Redis at {url}")
