import copy
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from api.security import AdminAuth, JWTAuth, WithdrawAuth

DENIED_PREFIXES = (
    "/api/v1/payment",
    "/api/v1/verify",
    "/api/v1/scheduling",
    "/api/v1/google-analytics",
    "/api/v1/lab",
    "/api/v1/product/secret",
    "/api/v1/kakao",
    "/api/v2/kakao",
    "/api/v1/apple",
    "/api/v2/apple",
    "/api/v1/toss",
    "/api/v1/auth",
)
DENIED_PHRASES = (
    "삭제",
    "탈퇴",
    "결제",
    "승인",
    "비밀번호",
    "로그인",
    "인증",
    "선물",
    "발급",
    "웹훅",
    "연결 해제",
    "초대",
    "재발송",
    "nicepay",
    "읽음 처리",
    "조회수 증가",
    "리워드 증가",
    "푸시 알림 테스트",
)
CREATE_HINTS = ("생성", "등록", "작성", "조회")
PAID_SUMMARY_PHRASES = ("AI 메시지", "이미지 생성", "학습 시작", "생성 요청")
AUTH_ME_PATH = "/api/v1/auth/me"
_PATH_SEGMENT = re.compile(r"[^A-Za-z0-9_]")

# 플러그인 스킬이 안내하는 도구만 공개한다.
WORKSPACE_RECORD_PATCH = ("PATCH", "/api/v1/workspace/record/{record_id}")
WORKBOT_PATCH = ("PATCH", "/api/v1/workbot/{workbot_id}")
WORKBOT_RUN = ("POST", "/api/v1/workbot/{workbot_id}/run")
PUBLIC_ENDPOINTS = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/notice"),
        ("GET", "/api/v1/notice/{notice_id}"),
        ("GET", "/api/v1/notification"),
        ("GET", "/api/v1/notification/unread-count"),
        ("GET", "/api/v1/workspace"),
        ("GET", "/api/v1/workspace/database"),
        ("GET", "/api/v1/workspace/database/{database_id}"),
        ("GET", "/api/v1/workspace/{workspace_id}/member"),
        ("GET", "/api/v1/workspace/record/{record_id}"),
        ("POST", "/api/v1/workspace/query"),
        ("POST", "/api/v1/workspace/database/{database_id}/record"),
        WORKSPACE_RECORD_PATCH,
        ("GET", "/api/v1/workbot"),
        ("GET", "/api/v1/workbot/stats"),
        ("GET", "/api/v1/workbot/run"),
        ("POST", "/api/v1/workbot"),
        WORKBOT_PATCH,
        WORKBOT_RUN,
    }
)
OPEN_WORLD_POSTS = frozenset()
# 조회처럼 보이지만 공개 조회수를 올리는 GET입니다.
VIEW_COUNT_GETS = frozenset(
    {
        ("GET", "/api/v1/notice/{notice_id}"),
    }
)
# 호출자의 데이터를 덮어쓰거나 지우는 쓰기입니다. 공개 게시는 아닙니다.
DESTRUCTIVE_WRITES = frozenset()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method: str
    path: str
    summary: str
    description: str
    input_schema: dict[str, Any]
    accepts_path: bool
    accepts_query: bool
    accepts_body: bool


def full_path(prefix: str, path: str) -> str:
    prefix = "/" + prefix.strip("/")
    if prefix == "/":
        prefix = ""
    suffix = path.strip("/")
    if not suffix:
        return prefix or "/"
    return f"{prefix}/{suffix}"


def tool_name(method: str, path: str) -> str:
    parts = [method.lower()]
    for segment in path.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            parts.append("by_" + segment[1:-1])
            continue
        cleaned = _PATH_SEGMENT.sub("_", segment).strip("_")
        if cleaned:
            parts.append(cleaned)
    return "_".join(parts)


def _unique_name(base: str, used: set[str]) -> str:
    name = base[:128]
    if name not in used:
        used.add(name)
        return name
    index = 2
    while True:
        suffix = f"_{index}"
        candidate = base[: 128 - len(suffix)] + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _callbacks(operation: Any) -> list[Any]:
    return list(operation.auth_callbacks or [])


def is_blocked_auth(operation: Any) -> bool:
    return any(isinstance(callback, (AdminAuth, WithdrawAuth)) for callback in _callbacks(operation))


def is_customer_auth(operation: Any) -> bool:
    callbacks = _callbacks(operation)
    if not callbacks or is_blocked_auth(operation):
        return False
    return any(isinstance(callback, JWTAuth) for callback in callbacks)


def has_denied_phrase(path: str, summary: str) -> bool:
    blob = f"{path} {summary}".lower()
    return any(phrase.lower() in blob for phrase in DENIED_PHRASES)


def is_denied_prefix(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in DENIED_PREFIXES)


def is_paid_external(method: str, path: str, summary: str) -> bool:
    if method == "POST" and (
        path == "/api/v1/train"
        or path.startswith("/api/v1/train/")
        or path == "/api/v1/generate"
        or path.startswith("/api/v1/generate/")
    ):
        return True
    return any(phrase in summary for phrase in PAID_SUMMARY_PHRASES)


def has_upload(operation: Any) -> bool:
    for model in operation.models:
        if getattr(model, "__ninja_param_source__", None) in {"file", "form"}:
            return True
    return False


def is_workspace_record_patch(method: str, path: str) -> bool:
    return (method, path) == WORKSPACE_RECORD_PATCH


def is_workbot_patch(method: str, path: str) -> bool:
    return (method, path) == WORKBOT_PATCH


def is_exposed(method: str, path: str, operation: Any) -> bool:
    if (method, path) not in PUBLIC_ENDPOINTS:
        return False
    if method not in {"GET", "POST"} and not is_workspace_record_patch(
        method, path
    ) and not is_workbot_patch(method, path):
        return False
    if not operation.include_in_schema or operation.deprecated:
        return False
    if has_upload(operation) or "{user_id}" in path:
        return False
    summary = operation.summary or ""
    if is_paid_external(method, path, summary):
        return False
    if "[A]" in summary and "[C]" not in summary:
        return False
    if path.startswith("/api/v1/myrealtrip") and not is_customer_auth(operation):
        return False
    if path == AUTH_ME_PATH and method == "GET":
        return True
    if is_denied_prefix(path):
        return False
    if method == "GET":
        if is_blocked_auth(operation):
            return False
        return is_customer_auth(operation) or not _callbacks(operation)
    if is_workspace_record_patch(method, path) or is_workbot_patch(method, path):
        if not is_customer_auth(operation):
            return False
        return "수정" in summary
    if (method, path) == WORKBOT_RUN:
        if not is_customer_auth(operation):
            return False
        return "실행" in summary
    if path.startswith("/api/v1/auth"):
        return False
    if not is_customer_auth(operation):
        return False
    return any(hint in summary for hint in CREATE_HINTS)


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs") or {}

    def walk(node: Any, stack: set[str]) -> Any:
        if isinstance(node, list):
            return [walk(item, stack) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            if name in stack or name not in definitions:
                return {"type": "object"}
            stack.add(name)
            resolved = walk(copy.deepcopy(definitions[name]), stack)
            stack.remove(name)
            extras = {
                key: walk(value, stack) for key, value in node.items() if key != "$ref"
            }
            if isinstance(resolved, dict):
                resolved.update(extras)
                return resolved
            return resolved
        return {
            key: walk(value, stack) for key, value in node.items() if key != "$defs"
        }

    resolved = walk(schema, set())
    if isinstance(resolved, dict):
        resolved.pop("$defs", None)
    return resolved


def _schema_of(model: type[BaseModel]) -> dict[str, Any]:
    try:
        return inline_schema(model.model_json_schema())
    except Exception:
        return {"type": "object", "additionalProperties": True}


def _body_schema(model: type[BaseModel]) -> dict[str, Any]:
    varname = getattr(model, "__read_from_single_attr__", None)
    field = model.model_fields.get(varname) if varname else None
    annotation = getattr(field, "annotation", None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _schema_of(annotation)
    return _schema_of(model)


def _model_for(operation: Any, source: str) -> type[BaseModel] | None:
    for model in operation.models:
        if getattr(model, "__ninja_param_source__", None) == source:
            return model
    return None


def _section_schema(model: type[BaseModel] | None, *, body: bool = False) -> dict[str, Any] | None:
    if model is None:
        return None
    schema = _body_schema(model) if body else _schema_of(model)
    if not schema.get("properties") and schema.get("additionalProperties") is not True:
        return None
    return schema


def build_input_schema(operation: Any) -> tuple[dict[str, Any], bool, bool, bool]:
    path_schema = _section_schema(_model_for(operation, "path"))
    query_schema = _section_schema(_model_for(operation, "query"))
    body_schema = _section_schema(_model_for(operation, "body"), body=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    if path_schema is not None:
        properties["path_params"] = path_schema
        if path_schema.get("required"):
            required.append("path_params")
    if query_schema is not None:
        properties["query"] = query_schema
    if body_schema is not None:
        properties["body"] = body_schema
        required.append("body")
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema, path_schema is not None, query_schema is not None, body_schema is not None


def tool_safety(method: str, path: str) -> dict[str, Any]:
    """OpenAI 심사에 필요한 hint와 한 문장 justification입니다."""
    key = (method, path)
    view_count = key in VIEW_COUNT_GETS
    open_world = key in OPEN_WORLD_POSTS
    destructive = open_world or key in DESTRUCTIVE_WRITES
    read_only = method == "GET" and not view_count
    if view_count:
        justifications = {
            "read_only_justification": "글 내용은 바꾸지 않지만 공개 조회수를 1 올립니다.",
            "open_world_justification": "새 글을 올리지 않고 해당 글의 조회 횟수만 증가합니다.",
            "destructive_justification": "글, 댓글, 계정 데이터를 지우거나 덮어쓰지 않습니다.",
        }
    elif read_only:
        justifications = {
            "read_only_justification": "연결된 계정의 데이터를 조회만 하며 저장소를 바꾸지 않습니다.",
            "open_world_justification": "KOC ERP API만 호출하고 공개 인터넷에 글을 올리지 않습니다.",
            "destructive_justification": "삭제, 덮어쓰기, 권한 회수처럼 되돌리기 어려운 동작을 하지 않습니다.",
        }
    elif open_world:
        justifications = {
            "read_only_justification": "공개 글을 남겨 상태를 바꿉니다.",
            "open_world_justification": "다른 사용자가 볼 수 있는 글이나 댓글을 게시합니다.",
            "destructive_justification": "플러그인에는 삭제 도구가 없어 게시된 글을 이 연결로 되돌릴 수 없습니다.",
        }
    else:
        justifications = {
            "read_only_justification": "연결된 계정의 데이터에 기록을 저장하므로 조회 전용이 아닙니다.",
            "open_world_justification": "변경은 호출자의 데이터 안에만 있고 외부 공개 게시가 아닙니다.",
            "destructive_justification": "기록을 추가하거나 저장하며 기존 데이터를 지우거나 결제하지 않습니다.",
        }
    return {
        "read_only": read_only,
        "open_world": open_world,
        "destructive": destructive,
        "justifications": justifications,
    }


def _description(method: str, path: str, summary: str, detail: str) -> str:
    lines = [summary or f"{method} {path}"]
    if detail and detail != summary:
        lines.append(detail.strip())
    lines.append(f"{method} {path}")
    lines.append(
        "path_params, query, body 중 이 API에 필요한 값만 넣습니다. 사용자는 토큰으로 결정됩니다."
    )
    if method == "GET" and path == AUTH_ME_PATH:
        lines.append(
            "연결된 계정을 답할 때는 email과 name을 알려 줍니다. 정수 사용자 id는 이 응답에 없으므로 말하지 않습니다."
        )
    if (method, path) in VIEW_COUNT_GETS:
        lines.append(
            "이 조회는 해당 글의 공개 조회수를 1 올립니다. 글 내용과 댓글은 바꾸지 않습니다."
        )
    if method == "POST":
        lines.append("이 호출은 데이터를 만들 수 있습니다. 실패해도 자동으로 다시 호출하지 않습니다.")
    if method == "PATCH":
        lines.append("이 호출은 레코드 값을 수정합니다. 레코드를 지우지는 않습니다.")
    lines.append(tool_safety(method, path)["justifications"]["read_only_justification"])
    text = "\n".join(lines)
    return text[:4000]


def build_catalog() -> list[ToolSpec]:
    from config.urls import base_api

    used: set[str] = set()
    specs: list[ToolSpec] = []
    for prefix, router in base_api._routers:
        for route_path, path_view in router.path_operations.items():
            for operation in path_view.operations:
                for method in operation.methods:
                    http_method = method.upper()
                    path = full_path(prefix, route_path)
                    if not is_exposed(http_method, path, operation):
                        continue
                    summary = operation.summary or operation.view_func.__name__
                    schema, accepts_path, accepts_query, accepts_body = build_input_schema(
                        operation
                    )
                    specs.append(
                        ToolSpec(
                            name=_unique_name(tool_name(http_method, path), used),
                            method=http_method,
                            path=path,
                            summary=summary,
                            description=_description(
                                http_method,
                                path,
                                summary,
                                operation.description or "",
                            ),
                            input_schema=schema,
                            accepts_path=accepts_path,
                            accepts_query=accepts_query,
                            accepts_body=accepts_body,
                        )
                    )
    specs.sort(key=lambda spec: (spec.path, spec.method))
    return specs
