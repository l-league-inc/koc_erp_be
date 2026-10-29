import jwt
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import AppRegistryNotReady
from django.conf import settings


class CustomAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        try:
            # 지연 로드로 get_user_model()을 여기서 호출
            User = get_user_model()

            # 쿠키에서 토큰 추출
            headers = dict(scope['headers'])
            cookie_header = headers.get(b'cookie', b'').decode()
            cookies = {cookie.split('=')[0].strip(): cookie.split('=')[1].strip() 
                       for cookie in cookie_header.split(';') if cookie}
            token = cookies.get('access')

            if token:
                try:
                    # 토큰 검증
                    payload = jwt.decode(
                        token, settings.SECRET_KEY, algorithms=["HS256"]
                    )
                    env = payload.get("env")
                    if env != settings.DJANGO_ENV_NAME:
                        scope["user"] = None
                        return await self.inner(scope, receive, send)
                    user_id = payload["user_id"]
                    user = await self.get_user(User, user_id)
                    if user:
                        scope["user"] = user
                    else:
                        scope["user"] = None
                except jwt.ExpiredSignatureError:
                    scope["user"] = None
                except jwt.InvalidTokenError:
                    scope["user"] = None
            else:
                scope["user"] = None
        except AppRegistryNotReady:
            scope["user"] = None
        return await self.inner(scope, receive, send)

    @database_sync_to_async
    def get_user(self, User, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
