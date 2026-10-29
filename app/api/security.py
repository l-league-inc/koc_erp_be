from ninja.security import HttpBearer
from django.http import HttpRequest
from django.contrib.auth import get_user_model
from django.core.cache import cache
import jwt
from django.conf import settings
from django.utils import timezone
from ninja.errors import HttpError
from typing import Optional, Any


User = get_user_model()

AUTH_CACHE_TTL = getattr(settings, "CACHE_TTL_AUTH", 60)


async def invalidate_auth_cache(user_id: int) -> None:
    """유저 정보 변경(플랜 업그레이드, 정지, 탈퇴) 시 호출하여 인증 캐시를 무효화합니다."""
    await cache.adelete(f"auth_user_{user_id}")


async def get_user_from_access_token(token: str) -> Optional[User]:
    """액세스 토큰의 서명, 만료, env를 검증하고 사용자를 반환합니다."""
    try:
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
                "require": ["exp"],
            },
        )
        audience = decoded.get("aud")
        if isinstance(audience, str):
            audiences = {audience}
        elif isinstance(audience, list):
            audiences = set(audience)
        else:
            audiences = set()
        if audiences and settings.MCP_RESOURCE_URL not in audiences:
            return None
        user_id = decoded.get("user_id")
        env = decoded.get("env")
        if env != settings.DJANGO_ENV_NAME:
            return None

        cache_key = f"auth_user_{user_id}"
        user = await cache.aget(cache_key)

        if user is None:
            try:
                user = await User.objects.aget(id=user_id)
            except User.DoesNotExist:
                return None
            await cache.aset(cache_key, user, timeout=AUTH_CACHE_TTL)

        return user

    except jwt.ExpiredSignatureError:
        return None
    except jwt.MissingRequiredClaimError:
        return None
    except jwt.DecodeError:
        return None
    except jwt.InvalidAlgorithmError:
        return None
    except User.DoesNotExist:
        return None
    return None


class JWTAuth(HttpBearer):
    async def __call__(self, request: HttpRequest) -> Optional[Any]:
        headers = request.headers
        auth_value = headers.get(self.header)

        if not auth_value:
            token = request.COOKIES.get("access")
            if token:
                return await self.authenticate(request, token)
            return None

        parts = auth_value.split(" ")
        if parts[0].lower() != self.openapi_scheme:
            return None

        token = " ".join(parts[1:])
        return await self.authenticate(request, token)

    async def authenticate(self, request, token):
        return await get_user_from_access_token(token)


class ActiveUserAuth(JWTAuth):
    async def authenticate(self, request, token):
        user = await super().authenticate(request, token)
        if user is None:
            return None

        if user.status == User.UserStatusChoice.WITHDRAW:
            if timezone.make_aware(user.withdraw_at) + timezone.timedelta(
                days=7
            ) > timezone.make_aware(timezone.now()):
                raise HttpError(452, "탈퇴한 계정입니다.")
            raise HttpError(403, "탈퇴한 계정입니다.")

        if user.status == User.UserStatusChoice.SUSPENDED:
            raise HttpError(403, "관리자에 의해 정지된 계정입니다.")

        return user


jwt_auth = ActiveUserAuth()


class AdminAuth(JWTAuth):
    async def authenticate(self, request, token):
        user = await super().authenticate(request, token)
        if user and user.permission_type == User.UserPermissionTypeChoices.ADMIN:
            return user
        return None


admin_auth = AdminAuth()


class WithdrawAuth(JWTAuth):
    async def authenticate(self, request, token):
        user = await super().authenticate(request, token)
        if (
            user
            and user.status == User.UserStatusChoice.WITHDRAW
            and user.withdraw_at
            and (
                timezone.make_aware(user.withdraw_at) + timezone.timedelta(days=7)
                > timezone.make_aware(timezone.now())
            )
        ):
            return user

        return None


withdraw_auth = WithdrawAuth()
