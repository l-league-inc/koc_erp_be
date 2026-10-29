from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations

from mcp_server.auth import JwtAsgiMiddleware
from mcp_server.catalog import ToolSpec, build_catalog, tool_safety
from mcp_server.executor import AsgiApiTransport, execute_tool


def _handler(spec: ToolSpec, transport: AsgiApiTransport):
    async def handler(
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> str:
        return await execute_tool(spec, transport, path_params, query, body)

    handler.__name__ = spec.name
    return handler


def _annotations(spec: ToolSpec) -> ToolAnnotations:
    safety = tool_safety(spec.method, spec.path)
    return ToolAnnotations(
        read_only_hint=safety["read_only"],
        open_world_hint=safety["open_world"],
        destructive_hint=safety["destructive"],
        idempotent_hint=safety["read_only"],
    )


def _meta(spec: ToolSpec) -> dict[str, Any]:
    return {"justifications": tool_safety(spec.method, spec.path)["justifications"]}


def build_mcp_http(django_app: Any) -> tuple[Any, Any]:
    """Stateless Streamable HTTP 앱과 세션 매니저를 만듭니다."""
    transport = AsgiApiTransport(django_app)
    server = MCPServer(
        name="koc_erp",
        instructions=(
            "KOC ERP API입니다. 호출자의 JWT에 묶인 데이터만 조회하거나 생성합니다. "
            "결제, 로그인, 삭제, 주문 생성, 관리자 기능은 제공하지 않습니다."
        ),
    )
    for spec in build_catalog():
        tool = server._tool_manager.add_tool(
            _handler(spec, transport),
            name=spec.name,
            title=spec.summary[:120],
            description=spec.description,
            annotations=_annotations(spec),
            meta=_meta(spec),
            structured_output=False,
        )
        tool.parameters = spec.input_schema

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
        host="0.0.0.0",
    )
    return JwtAsgiMiddleware(app), server._lowlevel_server._session_manager
