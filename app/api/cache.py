from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.db.models import QuerySet


def cached_response(cache_key_input: str, timeout: int = settings.CACHE_TTL):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = cache_key_input.format(**kwargs)

            cached_data = await cache.aget(cache_key)
            if cached_data is not None:
                return cached_data

            response = await func(*args, **kwargs)
            value: object = list(response) if isinstance(response, QuerySet) else response
            await cache.aset(cache_key, value, timeout)
            return value

        return wrapper

    return decorator
