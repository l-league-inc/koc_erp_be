import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from ninja.errors import HttpError

from assistant import llm
from assistant.models import AgentMessage, AgentSession, ProposedAction
from workspace.models import RecordActivity
from workspace.utils import (
    accessible_databases,
    create_record,
    get_membership,
    get_record,
    list_members,
    query_records,
    serialize_database,
    update_record,
)

_MAX_ROUNDS = 5
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_members",
            "description": "워크스페이스 멤버의 이름과 user_id를 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": "업무 영역 목록을 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_database_schema",
            "description": "영역 스키마와 보기를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {"database_slug": {"type": "string"}},
                "required": ["database_slug"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_records",
            "description": "레코드를 조회합니다. 저장하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_slug": {"type": "string"},
                    "q": {"type": "string"},
                    "filters": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_record",
            "description": "레코드 생성 초안을 만듭니다. 사용자가 확정하기 전에는 저장하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_slug": {"type": "string"},
                    "title": {"type": "string"},
                    "values": {"type": "object"},
                    "blocks": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["database_slug", "title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_record",
            "description": "레코드 수정 초안을 만듭니다. 사용자가 확정하기 전에는 저장하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "values": {"type": "object"},
                },
                "required": ["record_id"],
                "additionalProperties": False,
            },
        },
    },
]


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def serialize_action(action: ProposedAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "kind": action.kind,
        "status": action.status,
        "payload": action.payload or {},
        "result": action.result or {},
    }


def serialize_message(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
    }


def serialize_session(session: AgentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "workspace_id": session.workspace_id,
        "database_slug": session.database_slug,
        "created_at": session.created_at,
    }


def _session(user, session_id: int) -> AgentSession:
    session = AgentSession.objects.filter(id=session_id, user=user).first()
    if session is None:
        raise HttpError(404, "대화를 찾을 수 없습니다.")
    return session


def _database(user, workspace_id: int, slug: str):
    database = (
        accessible_databases(user).filter(workspace_id=workspace_id, slug=slug).first()
    )
    if database is None:
        raise HttpError(404, "데이터베이스를 찾을 수 없습니다.")
    return database


def _scoped_slug(session: AgentSession, requested: str) -> str:
    cleaned = (requested or "").strip()
    if session.database_slug and cleaned and cleaned != session.database_slug:
        raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")
    return cleaned or session.database_slug


def create_session(user, workspace_id: int, database_slug: str) -> dict[str, Any]:
    get_membership(user, workspace_id)
    slug = (database_slug or "").strip()
    if slug:
        _database(user, workspace_id, slug)
    session = AgentSession.objects.create(
        user=user,
        workspace_id=workspace_id,
        database_slug=slug,
    )
    return serialize_session(session)


def _history(session: AgentSession) -> list[dict[str, str]]:
    messages = list(session.messages.order_by("-id")[:20])
    messages.reverse()
    return [{"role": message.role, "content": message.content} for message in messages]


def _system_prompt(session: AgentSession) -> str:
    scope = session.database_slug or "전체"
    return (
        "당신은 KOC 워크스페이스 업무 도우미입니다. "
        f"워크스페이스 id는 {session.workspace_id}이고 범위는 {scope}입니다. "
        "멤버, 스키마, 레코드는 도구로 조회합니다. "
        "레코드를 만들거나 고칠 때는 propose 도구만 사용하고, 저장이 끝났다고 말하지 않습니다. "
        "담당자는 list_members의 user_id를 사용합니다."
    )


def _dispatch(session: AgentSession, user, name: str, arguments: dict[str, Any], created: list[int]) -> Any:
    if name == "list_members":
        return list_members(user, session.workspace_id)
    if name == "list_databases":
        databases = accessible_databases(user).filter(workspace_id=session.workspace_id)
        if session.database_slug:
            databases = databases.filter(slug=session.database_slug)
        return [serialize_database(database) for database in databases.order_by("position", "id")]
    if name == "get_database_schema":
        slug = _scoped_slug(session, str(arguments.get("database_slug") or ""))
        if not slug:
            raise HttpError(400, "영역 slug가 필요합니다.")
        return serialize_database(_database(user, session.workspace_id, slug), detail=True)
    if name == "query_records":
        slug = _scoped_slug(session, str(arguments.get("database_slug") or ""))
        filters = arguments.get("filters") or []
        keyword = str(arguments.get("q") or "")
        if slug:
            return query_records(
                user,
                {"database_slug": slug, "filters": filters, "q": keyword, "page": 1, "page_size": 20},
            )
        rows: list[dict[str, Any]] = []
        total = 0
        databases = accessible_databases(user).filter(workspace_id=session.workspace_id)
        for database in databases:
            result = query_records(
                user,
                {
                    "database_id": database.id,
                    "filters": filters,
                    "q": keyword,
                    "page": 1,
                    "page_size": 20,
                },
            )
            total += result["count"]
            rows.extend(result["data"])
        return {"count": total, "page": 1, "page_size": 20, "data": rows[:20]}
    if name == "propose_create_record":
        slug = _scoped_slug(session, str(arguments.get("database_slug") or ""))
        title = str(arguments.get("title") or "").strip()
        if not slug or not title:
            raise HttpError(400, "영역과 제목이 필요합니다.")
        _database(user, session.workspace_id, slug)
        values = arguments.get("values") or {}
        blocks = arguments.get("blocks") or []
        if not isinstance(values, dict) or not isinstance(blocks, list):
            raise HttpError(400, "값 형식이 올바르지 않습니다.")
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.CREATE_RECORD,
            payload={"database_slug": slug, "title": title, "values": values, "blocks": blocks},
        )
        created.append(action.id)
        return serialize_action(action)
    if name == "propose_update_record":
        record = get_record(user, int(arguments["record_id"]))
        if record.database.workspace_id != session.workspace_id:
            raise HttpError(404, "레코드를 찾을 수 없습니다.")
        if session.database_slug and record.database.slug != session.database_slug:
            raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")
        payload: dict[str, Any] = {"record_id": record.id}
        if arguments.get("title") is not None:
            payload["title"] = str(arguments["title"])
        if arguments.get("values") is not None:
            if not isinstance(arguments["values"], dict):
                raise HttpError(400, "값은 객체여야 합니다.")
            payload["values"] = arguments["values"]
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.UPDATE_RECORD,
            payload=payload,
        )
        created.append(action.id)
        return serialize_action(action)
    raise HttpError(400, "지원하지 않는 도구입니다.")


def send_message(user, session_id: int, content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise HttpError(400, "내용이 필요합니다.")
    if len(text) > 4000:
        raise HttpError(400, "내용은 4000자를 넘길 수 없습니다.")
    session = _session(user, session_id)
    AgentMessage.objects.create(session=session, role=AgentMessage.Role.USER, content=text)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(session)},
        *_history(session),
    ]
    created: list[int] = []
    answer = ""
    for _round in range(_MAX_ROUNDS):
        result = llm.complete(messages, _TOOLS)
        if not result["tool_calls"]:
            answer = result["content"].strip() or "요청을 확인했습니다."
            break
        messages.append(
            {
                "role": "assistant",
                "content": result["content"],
                "tool_calls": result["tool_calls"],
            }
        )
        for call in result["tool_calls"]:
            try:
                output = _dispatch(session, user, call["name"], call["arguments"], created)
            except HttpError as exc:
                output = {"error": exc.message}
            except (KeyError, TypeError, ValueError):
                output = {"error": "도구 인자가 올바르지 않습니다."}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _dump(output),
                }
            )
    else:
        answer = "요청을 마치지 못했습니다. 다시 말해 주세요."
    message = AgentMessage.objects.create(
        session=session,
        role=AgentMessage.Role.ASSISTANT,
        content=answer,
    )
    actions = ProposedAction.objects.filter(id__in=created).order_by("id")
    return {
        "message": serialize_message(message),
        "proposed_actions": [serialize_action(action) for action in actions],
    }


@transaction.atomic
def confirm_actions(user, session_id: int, action_ids: list[int]) -> dict[str, Any]:
    if not action_ids:
        raise HttpError(400, "확정할 초안이 필요합니다.")
    session = _session(user, session_id)
    actions = list(
        ProposedAction.objects.filter(
            session=session,
            id__in=action_ids,
            status=ProposedAction.Status.PENDING,
        ).order_by("id")
    )
    if len(actions) != len(set(action_ids)):
        raise HttpError(404, "확정할 초안을 찾을 수 없습니다.")
    records = []
    for action in actions:
        payload = action.payload or {}
        if action.kind == ProposedAction.Kind.CREATE_RECORD:
            database = _database(user, session.workspace_id, payload["database_slug"])
            saved = create_record(
                user,
                database.id,
                {
                    "title": payload.get("title"),
                    "values": payload.get("values") or {},
                    "blocks": payload.get("blocks") or [],
                },
                RecordActivity.Source.AGENT,
            )
        elif action.kind == ProposedAction.Kind.UPDATE_RECORD:
            saved = update_record(
                user,
                int(payload["record_id"]),
                {
                    "title": payload.get("title"),
                    "values": payload.get("values"),
                },
                RecordActivity.Source.AGENT,
            )
        else:
            raise HttpError(400, "지원하지 않는 초안입니다.")
        action.status = ProposedAction.Status.CONFIRMED
        action.result = {"record_id": saved["id"]}
        action.save(update_fields=["status", "result", "updated_at"])
        records.append(
            {"action_id": action.id, "record_id": saved["id"], "title": saved["title"]}
        )
    return {
        "proposed_actions": [serialize_action(action) for action in actions],
        "records": records,
    }
