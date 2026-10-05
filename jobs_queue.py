"""
Redis connection, RQ job queue and a small JSON cache
"""
import json
import logging
from datetime import timedelta

from redis import Redis
from rq import Queue, Retry

from config import Config

logger = logging.getLogger(__name__)

# Backoff for retried jobs (SMTP hiccups, rate limits)
DEFAULT_RETRY = Retry(max=5, interval=[30, 60, 120, 300, 600])

_redis = None


def get_redis():
    global _redis
    if _redis is None:
        _redis = Redis.from_url(Config.REDIS_URL, socket_timeout=5)
    return _redis


def set_redis(connection):
    """Swap the connection (tests use fakeredis)"""
    global _redis
    _redis = connection


def get_queue():
    return Queue("default", connection=get_redis(), is_async=not Config.QUEUE_SYNC)


def enqueue(func, *args, delay_seconds=0, retry=DEFAULT_RETRY, **kwargs):
    """Put a job on the queue; with a delay it waits for `rq worker --with-scheduler`"""
    queue = get_queue()
    if delay_seconds and queue.is_async:
        return queue.enqueue_in(
            timedelta(seconds=delay_seconds), func, *args, retry=retry, **kwargs
        )
    if delay_seconds:
        # Synchronous mode can't wait; delayed jobs are fallbacks, so skip them
        return None
    return queue.enqueue(func, *args, retry=retry, **kwargs)


def cache_get(key):
    try:
        raw = get_redis().get(key)
    except Exception as e:
        logger.warning(f"Cache read failed for {key}: {e}")
        return None
    return json.loads(raw) if raw else None


def cache_set(key, value, ttl_seconds):
    try:
        get_redis().setex(key, ttl_seconds, json.dumps(value, default=str))
    except Exception as e:
        logger.warning(f"Cache write failed for {key}: {e}")
