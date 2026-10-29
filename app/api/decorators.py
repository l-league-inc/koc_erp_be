from functools import wraps
from ninja.errors import HttpError
from django.conf import settings


def scheduling_only(view_func):
    """Scheduling 서버에서만 호출 가능하도록 제한하는 데코레이터"""

    @wraps(view_func)
    async def wrapper(request, *args, **kwargs):
        scheduling_key = request.headers.get("X-Scheduling-Key")
        if not scheduling_key:
            raise HttpError(401, "X-Scheduling-Key header is required")

        if scheduling_key != settings.SCHEDULING_SECRET_KEY:
            raise HttpError(403, "Invalid scheduling key")

        return await view_func(request, *args, **kwargs)

    return wrapper
