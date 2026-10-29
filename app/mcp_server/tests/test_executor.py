import json
from datetime import timedelta

import httpx
import jwt
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient, SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from mcp.server.mcpserver.exceptions import ToolError

from django.conf import settings

from config.routing import get_application
from mcp_server.auth import current_access_token, current_user_id
from mcp_server.catalog import ToolSpec, build_catalog
from mcp_server.executor import (
    ApiResult,
    AsgiApiTransport,
    execute_tool,
    internal_api_base_url,
    mcp_request_headers,
)
from mcp_server.oauth_server import _token_response
from user.utils import get_access_token

User = get_user_model()


class FakeTransport:
    def __init__(self, result: ApiResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def request(self, method, path, *, token, query, body):
        self.calls.append(
            {"method": method, "path": path, "token": token, "query": query, "body": body}
        )
        return self.result


def _spec(**overrides) -> ToolSpec:
    data = {
        "name": "get_api_v1_notice",
        "method": "GET",
        "path": "/api/v1/notice",
        "summary": "조회",
        "description": "조회",
        "input_schema": {"type": "object"},
        "accepts_path": False,
        "accepts_query": True,
        "accepts_body": False,
    }
    data.update(overrides)
    return ToolSpec(**data)


class ExecutorUnitTests(SimpleTestCase):
    def test_mcp_request_headers_mark_client(self):
        headers = mcp_request_headers("abc")
        self.assertEqual(headers["Authorization"], "Bearer abc")
        self.assertEqual(headers["X-KOC-Client"], "mcp")

    async def test_redacts_transport_payload_and_clamps_page_size(self):
        transport = FakeTransport(
            ApiResult(
                200,
                {"title": "일정", "password": "hidden", "access": "token-value"},
            )
        )
        token_state = current_access_token.set("user-token")
        user_state = current_user_id.set(7)
        try:
            rendered = await execute_tool(
                _spec(),
                transport,
                None,
                {"page_size": "all", "page": 1},
                {"ignored": True},
            )
        finally:
            current_access_token.reset(token_state)
            current_user_id.reset(user_state)

        self.assertIn("일정", rendered)
        self.assertNotIn("hidden", rendered)
        self.assertNotIn("token-value", rendered)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["token"], "user-token")
        self.assertIn(("page_size", "20"), transport.calls[0]["query"])
        self.assertIsNone(transport.calls[0]["body"])

    async def test_nested_filters_become_flat_query(self):
        transport = FakeTransport(ApiResult(200, {"items": []}))
        token_state = current_access_token.set("user-token")
        try:
            await execute_tool(
                _spec(),
                transport,
                None,
                {
                    "filters": {"completed": False, "search": "공지", "category": None},
                    "ninja_pagination": {"page": 1, "page_size": 100},
                },
                None,
            )
        finally:
            current_access_token.reset(token_state)
        query = transport.calls[0]["query"]
        self.assertIn(("completed", "false"), query)
        self.assertIn(("search", "공지"), query)
        self.assertIn(("page", "1"), query)
        self.assertIn(("page_size", "20"), query)
        self.assertFalse(any(key in {"filters", "ninja_pagination"} for key, _value in query))

    async def test_api_error_has_no_traceback(self):
        transport = FakeTransport(
            ApiResult(400, {"detail": "요청이 올바르지 않습니다.", "password": "hidden"})
        )
        token_state = current_access_token.set("user-token")
        try:
            with self.assertRaises(ToolError) as caught:
                await execute_tool(
                    _spec(method="POST", path="/api/v1/notice", accepts_body=True),
                    transport,
                    None,
                    None,
                    {},
                )
        finally:
            current_access_token.reset(token_state)
        message = str(caught.exception)
        self.assertIn("API 오류 (400)", message)
        self.assertIn("요청이 올바르지 않습니다.", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("hidden", message)

    async def test_missing_path_param(self):
        transport = FakeTransport(ApiResult(200, {}))
        token_state = current_access_token.set("user-token")
        try:
            with self.assertRaises(ToolError) as caught:
                await execute_tool(
                    _spec(path="/api/v1/notice/{notice_id}", accepts_path=True),
                    transport,
                    {},
                    None,
                    None,
                )
        finally:
            current_access_token.reset(token_state)
        self.assertIn("notice_id", str(caught.exception))
        self.assertEqual(transport.calls, [])

    async def test_auth_me_omits_integer_user_id(self):
        transport = FakeTransport(
            ApiResult(
                200,
                {
                    "id": 1093,
                    "email": "member@example.com",
                    "name": "김민수",
                    "profile": {"id": 44},
                },
            )
        )
        token_state = current_access_token.set("user-token")
        try:
            rendered = await execute_tool(
                _spec(
                    name="get_api_v1_auth_me",
                    method="GET",
                    path="/api/v1/auth/me",
                    accepts_query=False,
                ),
                transport,
                None,
                None,
                None,
            )
        finally:
            current_access_token.reset(token_state)
        body = json.loads(rendered)
        self.assertEqual(body["email"], "member@example.com")
        self.assertEqual(body["name"], "김민수")
        self.assertNotIn("id", body)
        self.assertEqual(body["profile"]["id"], 44)


class McpAuthTests(SimpleTestCase):
    async def test_missing_jwt_is_rejected(self):
        app = get_application()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Traceback", response.text)

    @override_settings(MCP_ENABLED=False)
    async def test_disabled_mcp_does_not_replace_api(self):
        app = get_application()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health-checker")
        self.assertEqual(response.status_code, 200)

    async def test_health_checker_stays_available(self):
        client = AsyncClient()
        response = await client.get("/api/health-checker")
        self.assertEqual(response.status_code, 200)

    @override_settings(
        ALLOWED_HOSTS=["api.koc-erp.co.kr"],
        MCP_RESOURCE_URL="https://api.koc-erp.co.kr/mcp",
    )
    async def test_internal_call_uses_allowed_api_host(self):
        self.assertEqual(internal_api_base_url(), "https://api.koc-erp.co.kr")
        app = get_application()
        result = await AsgiApiTransport(app).request(
            "GET",
            "/api/health-checker",
            token="",
            query=[],
            body=None,
        )
        self.assertEqual(result.status_code, 200, result.body)
