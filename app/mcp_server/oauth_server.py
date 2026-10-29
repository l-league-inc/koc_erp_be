import hashlib
import re
import secrets
import time
from base64 import b64decode, urlsafe_b64encode
from datetime import timedelta
from urllib.parse import unquote
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from django.conf import settings
from django.contrib.auth import aauthenticate, get_user_model
from django.utils import timezone

from mcp_server.models import OAuthAuthorizationCode, OAuthClient
from mcp_server.oauth_metadata import authorization_server_issuer
from user.models import Jwt
from user.utils import get_access_token, get_refresh_token

User = get_user_model()

OAUTH_SCOPE = "koc_erp"
CODE_TTL_SECONDS = 300
AUTHORIZE_FIELDS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
    "resource",
)
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_STABLE_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
_OAUTH_REDIRECT_HOSTS = frozenset(
    {
        "chatgpt.com",
        "platform.openai.com",
        "auth.openai.com",
    }
)
_BLOCKED_STATUSES = {
    User.UserStatusChoice.WITHDRAW,
    User.UserStatusChoice.SUSPENDED,
}


class OAuthClientError(Exception):
    """리다이렉트하면 안 되는 요청입니다."""

    def __init__(self, description: str) -> None:
        self.description = description
        super().__init__(description)


class RegistrationError(Exception):
    def __init__(self, description: str) -> None:
        self.description = description
        super().__init__(description)


class OAuthRedirectError(Exception):
    """허용된 redirect_uri로 돌려보낼 OAuth 오류입니다."""

    def __init__(self, error: str, description: str) -> None:
        self.error = error
        self.description = description
        super().__init__(description)


@dataclass(frozen=True)
class AuthorizeRequest:
    response_type: str
    client_id: str
    redirect_uri: str
    scope: str
    state: str
    code_challenge: str
    code_challenge_method: str
    resource: str


def authorization_server_metadata() -> dict[str, Any]:
    issuer = authorization_server_issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "scopes_supported": [OAUTH_SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }


def redirect_uri_allowed(redirect_uri: str) -> bool:
    if not _safe_text(redirect_uri) or not 1 <= len(redirect_uri) <= 2000:
        return False
    parts = urlsplit(redirect_uri)
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.fragment
        or parts.port not in (None, 443)
    ):
        return False
    if redirect_uri in _exact_redirect_uris():
        return True
    host = (parts.hostname or "").lower().rstrip(".")
    return host in _OAUTH_REDIRECT_HOSTS


def parse_authorize_request(params: Mapping[str, str]) -> AuthorizeRequest:
    values = {name: (params.get(name) or "").strip() for name in AUTHORIZE_FIELDS}
    if any(not _safe_text(value) for value in values.values()):
        raise OAuthClientError("요청에 허용되지 않는 문자가 있습니다.")
    if not values["client_id"] or not redirect_uri_allowed(values["redirect_uri"]):
        raise OAuthClientError("클라이언트 또는 리다이렉트 주소가 올바르지 않습니다.")

    request = AuthorizeRequest(
        response_type=values["response_type"],
        client_id=values["client_id"],
        redirect_uri=values["redirect_uri"],
        scope=values["scope"],
        state=values["state"],
        code_challenge=values["code_challenge"],
        code_challenge_method=values["code_challenge_method"],
        resource=values["resource"],
    )
    if request.response_type != "code":
        raise OAuthRedirectError(
            "unsupported_response_type", "response_type=code만 지원합니다."
        )
    if not _resource_matches(request.resource):
        raise OAuthRedirectError("invalid_target", "resource가 MCP 주소와 다릅니다.")
    if request.code_challenge_method != "S256" or not _CHALLENGE_RE.fullmatch(
        request.code_challenge
    ):
        raise OAuthRedirectError("invalid_request", "PKCE S256이 필요합니다.")
    if len(request.state) > 8192:
        raise OAuthRedirectError("invalid_request", "state가 너무 깁니다.")
    return request


def authorization_redirect_url(redirect_uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(redirect_uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def success_redirect_url(request: AuthorizeRequest, code: str) -> str:
    params = {
        "code": code,
        "iss": authorization_server_issuer(),
    }
    if request.state:
        params["state"] = request.state
    return authorization_redirect_url(request.redirect_uri, params)


def error_redirect_url(
    redirect_uri: str, error: str, description: str, state: str
) -> str:
    params = {
        "error": error,
        "error_description": description,
        "iss": authorization_server_issuer(),
    }
    if state:
        params["state"] = state
    return authorization_redirect_url(redirect_uri, params)


async def issue_authorization_code(user_id: int, request: AuthorizeRequest) -> str:
    code = secrets.token_urlsafe(32)
    await OAuthAuthorizationCode.objects.acreate(
        code_hash=_code_digest(code),
        user_id=user_id,
        client_id=request.client_id,
        redirect_uri=request.redirect_uri,
        code_challenge=request.code_challenge,
        resource=request.resource,
        expires_at=timezone.now() + timedelta(seconds=CODE_TTL_SECONDS),
    )
    return code


async def register_oauth_client(payload: dict[str, Any]) -> dict[str, Any]:
    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise RegistrationError("redirect_uris가 필요합니다.")
    cleaned: list[str] = []
    for uri in redirect_uris:
        if not isinstance(uri, str) or not redirect_uri_allowed(uri.strip()):
            raise RegistrationError("허용되지 않는 redirect_uri입니다.")
        cleaned.append(uri.strip())

    method = payload.get("token_endpoint_auth_method") or "none"
    if method not in {"none", "client_secret_basic", "client_secret_post"}:
        raise RegistrationError("지원하지 않는 token_endpoint_auth_method입니다.")
    grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list) or "authorization_code" not in grant_types:
        raise RegistrationError("authorization_code grant가 필요합니다.")
    response_types = payload.get("response_types") or ["code"]
    if response_types != ["code"]:
        raise RegistrationError("response_type=code만 지원합니다.")

    client_secret = "" if method == "none" else secrets.token_urlsafe(32)
    client = await OAuthClient.objects.acreate(
        client_id=secrets.token_urlsafe(32),
        client_secret=client_secret,
        token_endpoint_auth_method=method,
        redirect_uris=cleaned,
    )
    body: dict[str, Any] = {
        "client_id": client.client_id,
        "client_id_issued_at": int(time.time()),
        "client_secret_expires_at": 0,
        "redirect_uris": cleaned,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": OAUTH_SCOPE,
    }
    if client_secret:
        body["client_secret"] = client_secret
    return body


async def client_can_use_redirect(client_id: str, redirect_uri: str) -> bool:
    if client_id == settings.MCP_OAUTH_CLIENT_ID or _is_chatgpt_cimd_client(client_id):
        return True
    client = await OAuthClient.objects.filter(client_id=client_id).afirst()
    return client is not None and redirect_uri in list(client.redirect_uris or [])


async def exchange_authorization_code(
    params: Mapping[str, str], authorization: str = ""
) -> dict[str, Any]:
    client_id = await _require_client(params, authorization)
    code = (params.get("code") or "").strip()
    verifier = (params.get("code_verifier") or "").strip()
    redirect_uri = (params.get("redirect_uri") or "").strip()
    resource = (params.get("resource") or "").strip()
    if not code or not _VERIFIER_RE.fullmatch(verifier):
        return _token_error("invalid_request", "code와 code_verifier가 필요합니다.")
    if resource and not _resource_matches(resource):
        return _token_error("invalid_target", "resource가 MCP 주소와 다릅니다.")

    payload = await _consume_code(code)
    if payload is None:
        return _token_error("invalid_grant", "인증 코드가 올바르지 않거나 이미 사용되었습니다.")
    if (
        payload["client_id"] != client_id
        or payload["redirect_uri"] != redirect_uri
        or not _pkce_matches(verifier, payload["code_challenge"])
    ):
        return _token_error("invalid_grant", "PKCE 또는 리다이렉트 주소가 일치하지 않습니다.")

    user = await _active_user(int(payload["user_id"]))
    if user is None:
        return _token_error("invalid_grant", "사용할 수 없는 계정입니다.")
    return await _token_response(user)


async def exchange_refresh_token(
    params: Mapping[str, str], authorization: str = ""
) -> dict[str, Any]:
    await _require_client(params, authorization)
    refresh_token = (params.get("refresh_token") or "").strip()
    resource = (params.get("resource") or "").strip()
    if not refresh_token:
        return _token_error("invalid_request", "refresh_token이 필요합니다.")
    if resource and not _resource_matches(resource):
        return _token_error("invalid_target", "resource가 MCP 주소와 다릅니다.")
    if not _refresh_signature_ok(refresh_token):
        return _token_error("invalid_grant", "refresh 토큰이 올바르지 않습니다.")

    record = await Jwt.objects.select_related("user").filter(refresh=refresh_token).afirst()
    if record is None or _blocked(record.user):
        return _token_error("invalid_grant", "refresh 토큰이 올바르지 않습니다.")
    return await _token_response(record.user, record)


async def authenticate_oauth_user(email: str, password: str) -> tuple[Any | None, str]:
    user = await aauthenticate(None, email=email.strip(), password=password)
    if user is None:
        return None, "이메일 또는 비밀번호가 일치하지 않습니다."
    if _blocked(user):
        return None, "정지되었거나 탈퇴한 계정입니다."
    user.last_login = timezone.make_aware(timezone.now())
    await user.asave(update_fields=["last_login"])
    return user, ""


def _exact_redirect_uris() -> set[str]:
    extras = {
        item.strip()
        for item in settings.MCP_OAUTH_EXTRA_REDIRECT_URIS.split(",")
        if item.strip()
    }
    return {_STABLE_REDIRECT, *extras}


def _resource_matches(resource: str) -> bool:
    return resource.rstrip("/") == settings.MCP_RESOURCE_URL.rstrip("/")


def _is_chatgpt_cimd_client(client_id: str) -> bool:
    parts = urlsplit(client_id)
    if parts.scheme != "https" or (parts.hostname or "").lower() != "chatgpt.com":
        return False
    return parts.path == "/oauth/client.json" or (
        parts.path.startswith("/oauth/") and parts.path.endswith("/client.json")
    )


def _safe_text(value: str) -> bool:
    return "\r" not in value and "\n" not in value and "\x00" not in value


async def _require_client(params: Mapping[str, str], authorization: str) -> str:
    client_id, secret = _client_credentials(params, authorization)
    if not client_id:
        raise OAuthClientError("invalid_client")
    if client_id == settings.MCP_OAUTH_CLIENT_ID:
        expected = settings.MCP_OAUTH_CLIENT_SECRET
        if expected and not _secret_matches(secret, expected):
            raise OAuthClientError("invalid_client")
        return client_id
    if _is_chatgpt_cimd_client(client_id):
        return client_id
    client = await OAuthClient.objects.filter(client_id=client_id).afirst()
    if client is None:
        raise OAuthClientError("invalid_client")
    if client.token_endpoint_auth_method != "none" and not _secret_matches(
        secret, client.client_secret
    ):
        raise OAuthClientError("invalid_client")
    return client_id


def _client_credentials(params: Mapping[str, str], authorization: str) -> tuple[str, str]:
    if authorization.lower().startswith("basic "):
        encoded = authorization.split(" ", 1)[1].strip()
        try:
            decoded = b64decode(encoded, validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise OAuthClientError("invalid_client") from exc
        client_id, separator, secret = decoded.partition(":")
        if not separator:
            raise OAuthClientError("invalid_client")
        return unquote(client_id), unquote(secret)
    return (params.get("client_id") or "").strip(), (params.get("client_secret") or "").strip()


def _secret_matches(secret: str, expected: str) -> bool:
    return secrets.compare_digest(
        hashlib.sha256(secret.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def _pkce_matches(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed, challenge)


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def _consume_code(code: str) -> dict[str, Any] | None:
    now = timezone.now()
    row = await OAuthAuthorizationCode.objects.filter(
        code_hash=_code_digest(code),
        expires_at__gt=now,
    ).afirst()
    if row is None:
        return None
    consumed = await OAuthAuthorizationCode.objects.filter(
        pk=row.pk,
        expires_at__gt=now,
    ).aupdate(deleted_at=now)
    if consumed != 1:
        return None
    return {
        "user_id": row.user_id,
        "client_id": row.client_id,
        "redirect_uri": row.redirect_uri,
        "code_challenge": row.code_challenge,
        "resource": row.resource,
    }


def _refresh_signature_ok(token: str) -> bool:
    try:
        jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": True, "verify_exp": True, "require": ["exp"]},
        )
    except jwt.InvalidTokenError:
        return False
    return True


def _blocked(user: Any) -> bool:
    return user.status in _BLOCKED_STATUSES


async def _active_user(user_id: int) -> Any | None:
    try:
        user = await User.objects.aget(id=user_id)
    except User.DoesNotExist:
        return None
    if _blocked(user):
        return None
    return user


async def _token_response(user: Any, record: Jwt | None = None) -> dict[str, Any]:
    access, _access_exp = get_access_token(
        {
            "user_id": user.id,
            "env": settings.DJANGO_ENV_NAME,
            "aud": settings.MCP_RESOURCE_URL,
        }
    )
    if record is None:
        refresh, _refresh_exp = get_refresh_token()
        await Jwt.objects.acreate(user_id=user.id, access=access, refresh=refresh)
    else:
        refresh = record.refresh
        record.access = access
        await record.asave(update_fields=["access"])

    decoded = jwt.decode(
        access,
        key="",
        algorithms=["HS256"],
        options={"verify_signature": False},
    )
    return {
        "ok": True,
        "body": {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": max(0, int(decoded["exp"] - time.time())),
            "refresh_token": refresh,
            "scope": OAUTH_SCOPE,
        },
    }


def _token_error(error: str, description: str) -> dict[str, Any]:
    status = 401 if error == "invalid_client" else 400
    return {
        "ok": False,
        "status": status,
        "body": {"error": error, "error_description": description},
    }
