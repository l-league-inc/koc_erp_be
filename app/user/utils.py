import random
import secrets
import string
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from ninja.errors import HttpError

from user.models import PasswordEmailVerification

User = get_user_model()


def get_random(length):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def get_access_token(payload):
    exp = timezone.make_aware(timezone.now()) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRATION_TIME
    )
    return (
        jwt.encode(
            {
                "exp": exp,
                **payload,
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        ),
        exp,
    )


def decode_access_payload(token: str) -> dict:
    """앱 토큰은 aud 없이 통과하고, aud가 있으면 MCP 리소스와 같아야 합니다."""
    decoded = jwt.decode(
        token,
        key=settings.SECRET_KEY,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    audience = decoded.get("aud")
    if isinstance(audience, str):
        audiences = {audience}
    elif isinstance(audience, list):
        audiences = set(audience)
    else:
        audiences = set()
    if audiences and settings.MCP_RESOURCE_URL not in audiences:
        raise jwt.InvalidAudienceError("audience mismatch")
    return decoded


def get_refresh_token():
    exp = timezone.make_aware(timezone.now()) + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRATION_TIME
    )
    return (
        jwt.encode(
            {
                "exp": exp,
                "data": get_random(10),
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        ),
        exp,
    )


async def decodeJWT(bearer):
    if not bearer:
        return None

    token = bearer[7:]
    try:
        decoded = decode_access_payload(token)
        naive_datetime = datetime.fromtimestamp(decoded["exp"])
        exp_datetime = timezone.make_aware(naive_datetime, ZoneInfo("UTC"))
        if exp_datetime < timezone.make_aware(timezone.now()):
            raise HttpError(401, "토큰이 만료되었습니다.")
    except jwt.exceptions.ExpiredSignatureError:
        raise HttpError(401, "토큰이 만료되었습니다.")
    except jwt.exceptions.InvalidAudienceError:
        raise HttpError(401, "올바르지 않은 토큰입니다.")
    except jwt.exceptions.DecodeError:
        raise HttpError(401, "올바르지 않은 토큰입니다.")

    if decoded:
        env = decoded.get("env")
        if env != settings.DJANGO_ENV_NAME:
            return None  # 환경이 일치하지 않습니다.
        try:
            user = await User.objects.aget(id=decoded["user_id"])
            return user
        except User.DoesNotExist:
            return None


def set_cookie_jwt(
    response, access, refresh, access_exp, refresh_exp, reset=None, host=None
):
    domain = None
    if settings.DJANGO_ENV_NAME in ["main", "dev"]:
        domain = settings.SESSION_COOKIE_DOMAIN
    if host and host in ["localhost", "127.0.0.1"]:
        domain = None
    response.set_cookie(
        key="access",
        value=access,
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        secure=True,
        expires=access_exp,
        domain=domain,
    )
    response.set_cookie(
        key="refresh",
        value=refresh,
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        secure=True,
        expires=refresh_exp,
        domain=domain,
    )
    if reset:
        response.set_cookie(
            key="reset",
            value=reset,
            expires=access_exp,
            secure=True,
            samesite=settings.SESSION_COOKIE_SAMESITE,
            httponly=True,
            domain=domain,
        )
    return response


async def verify_token(token):
    # decode the token
    try:
        decoded_data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None

    # check if token as exipired
    exp = decoded_data["exp"]

    if datetime.now().timestamp() > exp:
        return None

    return decoded_data


async def middleware_decodeJWT(bearer):
    if not bearer:
        return None

    token = bearer[7:]

    try:
        decoded = decode_access_payload(token)
        naive_datetime = datetime.fromtimestamp(decoded["exp"])
        exp_datetime = timezone.make_aware(naive_datetime)
        if exp_datetime < timezone.make_aware(timezone.now()):
            return "TOKEN_EXPIRED"  # 토큰이 만료되었습니다.
    except jwt.exceptions.ExpiredSignatureError:
        return "TOKEN_EXPIRED"  # 토큰이 만료되었습니다.
    except jwt.exceptions.InvalidAudienceError:
        return "TOKEN_INVALID"  # 올바르지 않은 토큰입니다.
    except jwt.exceptions.DecodeError:
        return "TOKEN_INVALID"  # 올바르지 않은 토큰입니다.

    if decoded:
        env = decoded.get("env")
        if env != settings.DJANGO_ENV_NAME:
            return "TOKEN_ENV_MISMATCH"  # 환경이 일치하지 않습니다.
        try:
            user = await User.objects.aget(id=decoded["user_id"])
            return user
        except User.DoesNotExist:
            return "TOKEN_USER_NOT_FOUND"  # 토큰에 해당하는 사용자를 찾을 수 없습니다.


async def get_user(request):
    headers = request.headers
    auth_value = headers.get("Authorization")
    cookie_token = request.COOKIES.get("access", None)
    user = "NOT_LOGGED_IN"
    if cookie_token:
        user = await middleware_decodeJWT(f"Bearer {cookie_token}")
    elif auth_value:
        user = await middleware_decodeJWT(auth_value)
    return user


async def create_password_reset_token(user):
    token = secrets.token_urlsafe(32)
    await PasswordEmailVerification.objects.filter(
        user=user, is_verified=False
    ).adelete()
    verification = await PasswordEmailVerification.objects.acreate(
        user=user, token=token, is_verified=False
    )
    return verification


async def get_user_by_id(user_id):
    try:
        user = await User.objects.aget(id=user_id)
    except User.DoesNotExist:
        raise HttpError(404, "사용자를 찾을 수 없습니다.")
    return user


async def get_user_by_email(email):
    try:
        user = await User.objects.aget(email=email)
    except User.DoesNotExist:
        raise HttpError(404, "해당 이메일의 사용자를 찾을 수 없습니다.")
    return user


async def get_user_by_social_email(social_email):
    try:
        user = await User.objects.aget(social_email=social_email)
    except User.DoesNotExist:
        raise HttpError(404, "해당 이메일의 사용자를 찾을 수 없습니다.")
    return user


async def get_user_by_phone_number(phone_number):
    try:
        user = await User.objects.aget(phone_number=phone_number)
    except User.DoesNotExist:
        raise HttpError(404, "해당 전화번호의 사용자를 찾을 수 없습니다.")
    return user


async def validate_nickname_for_user(nickname: str, user_id: int) -> str:
    from user.nickname_utils import is_missing_nickname

    if is_missing_nickname(nickname):
        raise HttpError(400, "닉네임을 입력해주세요.")

    normalized_nickname = nickname.strip()
    if (
        await User.objects.filter(nickname=normalized_nickname)
        .exclude(id=user_id)
        .aexists()
    ):
        raise HttpError(400, "이미 사용중인 닉네임입니다.")

    return normalized_nickname


# 푸시 알림 동의
async def get_users_with_push_notification_permission():

    @sync_to_async
    def fetch_users():
        queryset = User.objects.filter(
            status=User.UserStatusChoice.ACTIVE,
            push_notification=True,
            fcm_token__isnull=False,
        ).all()
        return list(queryset)

    return await fetch_users()
