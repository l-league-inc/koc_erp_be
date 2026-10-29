import json
from contextvars import ContextVar
from typing import Any

from ninja.errors import HttpError

from api.security import jwt_auth
from mcp_server.oauth_metadata import www_authenticate_header

current_access_token: ContextVar[str | None] = ContextVar(
    "mcp_access_token", default=None
)
current_user_id: ContextVar[int | None] = ContextVar("mcp_user_id", default=None)


def bearer_token(scope: dict[str, Any]) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() != b"authorization":
            continue
        text = value.decode("latin-1")
        if not text.lower().startswith("bearer "):
            return None
        token = text[7:].strip()
        return token or None
    return None


async def _reject(receive: Any, send: Any, status: int, detail: str) -> None:
    while True:
        message = await receive()
        if message["type"] == "http.request" and not message.get("more_body", False):
            break
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if status == 401:
        headers.append(
            (b"www-authenticate", www_authenticate_header().encode())
        )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class JwtAsgiMiddleware:
    """MCP HTTP 입구에서 기존 활성 사용자 JWT를 검사합니다."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = bearer_token(scope)
        if not token:
            await _reject(receive, send, 401, "인증이 필요합니다.")
            return

        try:
            user = await jwt_auth.authenticate(None, token)
        except HttpError:
            await _reject(receive, send, 401, "인증이 필요합니다.")
            return

        if user is None:
            await _reject(receive, send, 401, "인증이 필요합니다.")
            return

        token_state = current_access_token.set(token)
        user_state = current_user_id.set(user.id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_access_token.reset(token_state)
            current_user_id.reset(user_state)
