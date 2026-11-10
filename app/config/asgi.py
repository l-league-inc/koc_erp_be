"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class AsgiLifespan:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    # 여기에 시작 시 필요한 로직을 추가하세요
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    # 여기에 종료 시 필요한 로직을 추가하세요
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await self.app(scope, receive, send)


from config.routing import get_application

# application = AsgiLifespan(get_asgi_application())
application = get_application()

# 서버 프로세스에서만 워크봇 예약 실행기를 띄운다. migrate 같은 관리 명령은 asgi를 읽지 않는다.
from assistant.scheduler import start_scheduler  # noqa: E402

start_scheduler()
