import json
import secrets
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from django.conf import settings
from django.utils import timezone

from mcp_server.models import OAuthSocialPending
from mcp_server.oauth_metadata import authorization_server_issuer
from mcp_server.oauth_server import AuthorizeRequest
from mcp_server.social_accounts import (
    SocialAccountConflict,
    resolve_apple_user,
    resolve_kakao_user,
)
from user.appleapi import generate_apple_client_secret
from user.models import User

PENDING_TTL_SECONDS = 600


class SocialLoginError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def kakao_redirect_uri() -> str:
    return f"{authorization_server_issuer()}/oauth/kakao/callback"


def apple_redirect_uri() -> str:
    return f"{authorization_server_issuer()}/oauth/apple/callback"


async def store_pending(request: AuthorizeRequest) -> str:
    key = secrets.token_urlsafe(24)
    await OAuthSocialPending.objects.acreate(
        state_key=key,
        payload=asdict(request),
        expires_at=timezone.now() + timedelta(seconds=PENDING_TTL_SECONDS),
    )
    return key


async def load_pending(key: str) -> AuthorizeRequest | None:
    row = await OAuthSocialPending.objects.filter(
        state_key=key,
        expires_at__gt=timezone.now(),
    ).afirst()
    if row is None or not isinstance(row.payload, dict):
        return None
    try:
        return AuthorizeRequest(**row.payload)
    except TypeError:
        return None


async def drop_pending(key: str) -> None:
    await OAuthSocialPending.objects.filter(state_key=key).aupdate(
        deleted_at=timezone.now()
    )


def kakao_authorize_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.KAKAO_REST_API_KEY,
            "redirect_uri": kakao_redirect_uri(),
            "response_type": "code",
            "state": state,
        }
    )
    return f"https://kauth.kakao.com/oauth/authorize?{query}"


def apple_authorize_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.APPLE_CLIENT_ID,
            "redirect_uri": apple_redirect_uri(),
            "response_type": "code",
            "state": state,
            "scope": "name email",
            "response_mode": "form_post",
        }
    )
    return f"https://appleid.apple.com/auth/authorize?{query}"


async def login_with_kakao_code(code: str) -> User:
    if not settings.KAKAO_REST_API_KEY:
        raise SocialLoginError("카카오 로그인이 설정되지 않았습니다.")
    redirect_uri = kakao_redirect_uri()
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://kauth.kakao.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_REST_API_KEY,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        token_body = token_response.json()
        access_token = token_body.get("access_token")
        if not access_token:
            raise SocialLoginError("카카오 로그인에 실패했습니다. 다시 시도해 주세요.")
        profile_response = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if profile_response.status_code != 200:
        raise SocialLoginError("카카오 사용자 정보를 가져오지 못했습니다.")
    profile = profile_response.json()
    kakao_user_id = profile.get("id")
    if not kakao_user_id:
        raise SocialLoginError("카카오 사용자 정보를 가져오지 못했습니다.")
    account = profile.get("kakao_account") or {}
    try:
        return await resolve_kakao_user(
            str(kakao_user_id),
            account.get("email"),
            _normalize_phone(account.get("phone_number")),
            account.get("gender"),
        )
    except SocialAccountConflict as exc:
        raise SocialLoginError(exc.message) from exc


async def login_with_apple_code(
    code: str, user_payload: str | None
) -> User:
    if not settings.APPLE_CLIENT_ID or not settings.APPLE_PRIVATE_KEY:
        raise SocialLoginError("애플 로그인이 설정되지 않았습니다.")
    try:
        client_secret = generate_apple_client_secret()
    except Exception as exc:
        raise SocialLoginError("애플 로그인이 설정되지 않았습니다.") from exc
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://appleid.apple.com/auth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": settings.APPLE_CLIENT_ID,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": apple_redirect_uri(),
            },
        )
    if token_response.status_code != 200:
        raise SocialLoginError("애플 로그인에 실패했습니다. 다시 시도해 주세요.")
    id_token = token_response.json().get("id_token")
    if not id_token:
        raise SocialLoginError("애플 로그인에 실패했습니다. 다시 시도해 주세요.")
    try:
        decoded = jwt.decode(id_token, options={"verify_signature": False})
    except Exception as exc:
        raise SocialLoginError("애플 로그인에 실패했습니다. 다시 시도해 주세요.") from exc
    apple_user_id = decoded.get("sub")
    if not apple_user_id:
        raise SocialLoginError("애플 사용자 정보를 가져오지 못했습니다.")
    try:
        return await resolve_apple_user(
            str(apple_user_id),
            decoded.get("email"),
            _apple_name(user_payload),
        )
    except SocialAccountConflict as exc:
        raise SocialLoginError(exc.message) from exc


def _normalize_phone(phone_number: str | None) -> str | None:
    import re

    if not phone_number:
        return None
    normalized = re.sub(r"^\+82\s", "0", phone_number)
    return re.sub(r"[^0-9]", "", normalized)


def _apple_name(user_payload: str | None) -> str | None:
    if not user_payload:
        return None
    try:
        parsed: Any = json.loads(user_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("name") or {}
    if not isinstance(name, dict):
        return None
    combined = f"{name.get('lastName', '')}{name.get('firstName', '')}".strip()
    return combined or None
