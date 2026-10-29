import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.auth import current_access_token, current_user_id
from mcp_server.catalog import AUTH_ME_PATH, ToolSpec
from mcp_server.redaction import omit_user_integer_ids, redact

logger = logging.getLogger("mcp_server")
_PATH_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ApiResult:
    status_code: int
    body: Any


class ApiTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        query: list[tuple[str, str]],
        body: Any,
    ) -> ApiResult:
        """기존 API를 한 번 호출합니다. 쓰기는 재시도하지 않습니다."""


def internal_api_base_url() -> str:
    """내부 호출 Host를 운영 ALLOWED_HOSTS에 있는 API 주소로 맞춥니다."""
    parts = urlsplit(settings.MCP_RESOURCE_URL)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return "https://api.koc-erp.co.kr"


class AsgiApiTransport:
    """같은 프로세스의 Django ASGI 앱을 호출합니다."""

    def __init__(self, app: Any, timeout: float = _REQUEST_TIMEOUT_SECONDS) -> None:
        self.app = app
        self.timeout = timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        query: list[tuple[str, str]],
        body: Any,
    ) -> ApiResult:
        transport = httpx.ASGITransport(app=self.app)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url=internal_api_base_url(),
                timeout=self.timeout,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params=query or None,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.TimeoutException as exc:
            raise ToolError("요청 시간이 초과되었습니다.") from exc
        except httpx.HTTPError as exc:
            raise ToolError("요청을 처리하지 못했습니다.") from exc
        return ApiResult(status_code=response.status_code, body=_parse_body(response))


def fill_path(template: str, params: dict[str, Any]) -> str:
    required = _PATH_PARAM.findall(template)
    missing = [name for name in required if name not in params]
    if missing:
        raise ToolError(f"path_params에 {', '.join(missing)}이 필요합니다.")
    unknown = [name for name in params if name not in required]
    if unknown:
        raise ToolError(f"알 수 없는 path_params입니다: {', '.join(unknown)}")

    def replace(match: re.Match[str]) -> str:
        value = params[match.group(1)]
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ToolError("path_params 값은 문자열이나 숫자여야 합니다.")
        text = str(value)
        if text == "" or "/" in text or "\\" in text or ".." in text:
            raise ToolError("path_params 값이 올바르지 않습니다.")
        return text

    return _PATH_PARAM.sub(replace, template)


def flatten_query(query: dict[str, Any]) -> dict[str, Any]:
    """Ninja FilterSchema와 페이지 인자는 쿼리 문자열의 평면 키로 받는다."""
    nested: dict[str, Any] = {}
    top: dict[str, Any] = {}
    for key, value in query.items():
        if isinstance(value, dict):
            for inner_key, inner_value in value.items():
                if inner_value is None:
                    continue
                nested[str(inner_key)] = inner_value
            continue
        top[str(key)] = value
    return {**nested, **top}


def clamp_page_size(query: dict[str, Any]) -> dict[str, Any]:
    limited = dict(query)
    max_page_size = settings.MCP_MAX_PAGE_SIZE
    for key in ("page_size", "limit"):
        if key not in limited:
            continue
        value = limited[key]
        if value == "all":
            limited[key] = max_page_size
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        limited[key] = min(number, max_page_size)
    return limited


def normalize_query(query: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            items.append((str(key), "true" if value else "false"))
            continue
        if isinstance(value, (int, float, str)):
            items.append((str(key), str(value)))
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (int, float, str, bool)):
                    items.append((str(key), str(item)))
                    continue
                raise ToolError(f"query.{key} 값이 올바르지 않습니다.")
            continue
        raise ToolError(f"query.{key} 값이 올바르지 않습니다.")
    return items


def safe_error(status_code: int, body: Any) -> str:
    detail = ""
    redacted = redact(body)
    if isinstance(redacted, dict):
        raw = redacted.get("detail", redacted.get("message"))
        if isinstance(raw, str):
            detail = raw
        elif raw is not None:
            detail = json.dumps(raw, ensure_ascii=False)
    elif isinstance(redacted, str):
        detail = redacted
    if "Traceback" in detail or len(detail) > 500:
        detail = "요청을 처리하지 못했습니다."
    if not detail:
        detail = "요청을 처리하지 못했습니다."
    return f"API 오류 ({status_code}): {detail}"


async def execute_tool(
    spec: ToolSpec,
    transport: ApiTransport,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
    body: Any,
) -> str:
    token = current_access_token.get()
    if not token:
        raise ToolError("인증이 필요합니다.")

    started = time.monotonic()
    status_code = 0
    try:
        path = fill_path(spec.path, path_params or {})
        query_items = normalize_query(
            clamp_page_size(flatten_query(query or {})) if spec.accepts_query else {}
        )
        payload = body if spec.accepts_body else None
        result = await transport.request(
            spec.method,
            path,
            token=token,
            query=query_items,
            body=payload,
        )
        status_code = result.status_code
        if status_code >= 400:
            raise ToolError(safe_error(status_code, result.body))
        payload = redact(result.body)
        if spec.method == "GET" and spec.path == AUTH_ME_PATH:
            payload = omit_user_integer_ids(payload)
        rendered = json.dumps(payload, ensure_ascii=False)
    except ToolError:
        logger.info(
            "mcp tool=%s user_id=%s status=%s elapsed_ms=%s",
            spec.name,
            current_user_id.get(),
            status_code or "error",
            int((time.monotonic() - started) * 1000),
        )
        raise
    except Exception:
        logger.info(
            "mcp tool=%s user_id=%s status=error elapsed_ms=%s",
            spec.name,
            current_user_id.get(),
            int((time.monotonic() - started) * 1000),
        )
        raise ToolError("요청을 처리하지 못했습니다.") from None

    logger.info(
        "mcp tool=%s user_id=%s status=%s elapsed_ms=%s",
        spec.name,
        current_user_id.get(),
        status_code,
        int((time.monotonic() - started) * 1000),
    )
    return rendered


def _parse_body(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            return response.json()
        except ValueError:
            return {"detail": "응답을 해석하지 못했습니다."}
    text = response.text
    if len(text) > 2000:
        text = text[:2000]
    return {"detail": text}
