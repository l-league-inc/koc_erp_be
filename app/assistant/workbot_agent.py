"""워크봇 `agent` 동작: 예약 시각마다 저장된 지시를 모델이 도구로 수행합니다."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone
from ninja.errors import HttpError

from assistant import llm
from assistant.agent import _TOOLS as _AGENT_TOOLS
from assistant.models import Workbot
from document.utils import get_file_detail, search_files
from workspace.models import RecordActivity
from workspace.utils import (
    accessible_databases,
    create_record,
    fold_date_range_aliases,
    get_record,
    list_members,
    query_records,
    serialize_database,
    update_record,
)

MAX_ROUNDS = 12
_READ_TOOLS = {
    "list_members",
    "list_databases",
    "get_database_schema",
    "query_records",
    "search_documents",
    "get_document",
}
_WEEKDAYS = "월화수목금토일"
_BLOCK_TYPES = (
    "paragraph, heading_1, heading_2, heading_3, bulleted_list, numbered_list, "
    "to_do, quote, divider, callout, code"
)

_WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_record",
            "description": (
                "레코드(페이지)를 만듭니다. 본문은 blocks에 채웁니다. "
                "blocks 없이 제목만 만들면 빈 페이지가 됩니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database_slug": {"type": "string"},
                    "title": {"type": "string"},
                    "values": {"type": "object"},
                    "blocks": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["database_slug", "title", "blocks"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_record",
            "description": "이미 있는 레코드의 제목·값·본문을 고칩니다. blocks를 주면 본문 전체가 바뀝니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "values": {"type": "object"},
                    "blocks": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["record_id"],
                "additionalProperties": False,
            },
        },
    },
]
TOOLS = [
    tool for tool in _AGENT_TOOLS if tool["function"]["name"] in _READ_TOOLS
] + _WRITE_TOOLS


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _database(bot: Workbot, owner, slug: str):
    database = (
        accessible_databases(owner).filter(workspace_id=bot.workspace_id, slug=slug).first()
    )
    if database is None:
        raise HttpError(404, "데이터베이스를 찾을 수 없습니다.")
    return database


def _prepare_values(database, values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise HttpError(400, "값은 객체여야 합니다.")
    folded = fold_date_range_aliases(database, values)
    known = set(database.properties.values_list("slug", flat=True))
    unknown = [slug for slug in folded if slug not in known]
    if unknown:
        raise HttpError(400, f"속성 {unknown[0]}을 찾을 수 없습니다.")
    return folded


def _system_prompt(bot: Workbot, owner, spec: dict[str, Any]) -> str:
    today = timezone.now()
    weekday = _WEEKDAYS[today.weekday()]
    confirm = (
        "이번 실행은 확인 후 반영이라 만들고 고치는 도구 호출은 저장되지 않고 대기열에 쌓입니다. "
        if spec.get("requires_confirmation")
        else ""
    )
    return (
        "당신은 KOC 워크봇입니다. 예약된 시각에 자동으로 실행되며 사용자에게 되물을 수 없습니다. "
        "아래 지시를 도구로 끝까지 수행하고, 마지막에 한 일을 한국어 한두 문장으로 요약해 답합니다. "
        "사용자에게 보이는 모든 문장은 한국어입니다.\n"
        f"워크봇 이름: {bot.name}\n"
        f"지시: {bot.instruction or bot.description or bot.name}\n"
        f"워크스페이스 id는 {bot.workspace_id}이고 기본 영역 slug는 {bot.database_slug}입니다. "
        f"지금은 {today.strftime('%Y-%m-%d %H:%M')} {weekday}요일이고 "
        f"실행 사용자 id는 {owner.id}입니다. 날짜 계산은 이 시각을 기준으로 합니다.\n"
        "규칙:\n"
        "- 멤버, 스키마, 레코드는 먼저 도구로 조회합니다. 추측해서 값을 만들지 않습니다.\n"
        "- values의 키는 get_database_schema에 있는 slug만 씁니다. "
        "날짜 범위는 그 date 속성에 {\"start\",\"end\"}로 넣습니다.\n"
        "- 페이지를 만들 때는 반드시 blocks로 본문을 채웁니다. 제목만 있는 빈 페이지는 만들지 않습니다. "
        "조회한 레코드가 있으면 그 내용을 정리해 본문에 넣습니다.\n"
        "- 블록 모양은 {\"type\":\"heading_2\",\"content\":{\"text\":\"...\"},\"children\":[]}이고 "
        f"type은 {_BLOCK_TYPES} 중 하나입니다.\n"
        "- 같은 일을 이미 했는지(같은 제목·기간의 레코드)를 query_records로 확인하고 있으면 새로 만들지 않습니다.\n"
        "- 조회 결과가 없으면 없다고 답하고 불필요한 레코드를 만들지 않습니다.\n"
        f"{confirm}"
    )


def _queue(pending: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    pending.append(item)
    return {"queued": True, "message": "확인 후 반영됩니다."}


def _create(
    bot: Workbot,
    owner,
    arguments: dict[str, Any],
    *,
    defer: bool,
    pending: list[dict[str, Any]],
    record_ids: list[int],
) -> Any:
    slug = str(arguments.get("database_slug") or bot.database_slug).strip()
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise HttpError(400, "제목이 필요합니다.")
    blocks = arguments.get("blocks") or []
    if not isinstance(blocks, list):
        raise HttpError(400, "본문 블록은 배열이어야 합니다.")
    database = _database(bot, owner, slug)
    values = _prepare_values(database, arguments.get("values") or {})
    if defer:
        return _queue(
            pending,
            {
                "kind": "create_record",
                "database_slug": slug,
                "title": title,
                "values": values,
                "blocks": blocks,
            },
        )
    saved = create_record(
        owner,
        database.id,
        {"title": title, "values": values, "blocks": blocks},
        RecordActivity.Source.AGENT,
    )
    record_ids.append(saved["id"])
    return {"record_id": saved["id"], "title": saved["title"]}


def _update(
    bot: Workbot,
    owner,
    arguments: dict[str, Any],
    *,
    defer: bool,
    pending: list[dict[str, Any]],
    record_ids: list[int],
) -> Any:
    record = get_record(owner, int(arguments["record_id"]))
    if record.database.workspace_id != bot.workspace_id:
        raise HttpError(404, "레코드를 찾을 수 없습니다.")
    data: dict[str, Any] = {}
    if arguments.get("title") is not None:
        data["title"] = str(arguments["title"])
    if arguments.get("values") is not None:
        data["values"] = _prepare_values(record.database, arguments["values"])
    if arguments.get("blocks") is not None:
        if not isinstance(arguments["blocks"], list):
            raise HttpError(400, "본문 블록은 배열이어야 합니다.")
        data["blocks"] = arguments["blocks"]
    if defer:
        return _queue(pending, {"kind": "update_record", "record_id": record.id, **data})
    saved = update_record(owner, record.id, data, RecordActivity.Source.AGENT)
    record_ids.append(saved["id"])
    return {"record_id": saved["id"], "title": saved["title"]}


def _dispatch(
    bot: Workbot,
    owner,
    name: str,
    arguments: dict[str, Any],
    *,
    defer: bool,
    pending: list[dict[str, Any]],
    record_ids: list[int],
) -> Any:
    if name == "list_members":
        return list_members(owner, bot.workspace_id)
    if name == "list_databases":
        databases = accessible_databases(owner).filter(workspace_id=bot.workspace_id)
        return [serialize_database(item) for item in databases.order_by("position", "id")]
    if name == "get_database_schema":
        slug = str(arguments.get("database_slug") or bot.database_slug).strip()
        return serialize_database(_database(bot, owner, slug), detail=True)
    if name == "query_records":
        slug = str(arguments.get("database_slug") or "").strip()
        payload: dict[str, Any] = {
            "workspace_id": bot.workspace_id,
            "filters": arguments.get("filters") or [],
            "q": str(arguments.get("q") or ""),
            "page": 1,
            "page_size": 20,
        }
        if slug:
            payload["database_slug"] = slug
        return query_records(owner, payload)
    if name == "search_documents":
        return search_files(owner, bot.workspace_id, str(arguments.get("q") or ""))
    if name == "get_document":
        return get_file_detail(owner, bot.workspace_id, int(arguments["file_id"]))
    if name == "create_record":
        return _create(bot, owner, arguments, defer=defer, pending=pending, record_ids=record_ids)
    if name == "update_record":
        return _update(bot, owner, arguments, defer=defer, pending=pending, record_ids=record_ids)
    raise HttpError(400, "지원하지 않는 도구입니다.")


def run_agent(bot: Workbot, owner, spec: dict[str, Any]) -> dict[str, Any]:
    """저장된 지시를 수행하고 요약·반영한 레코드·대기열을 돌려줍니다."""
    defer = bool(spec.get("requires_confirmation"))
    pending: list[dict[str, Any]] = []
    record_ids: list[int] = []
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(bot, owner, spec)},
        {"role": "user", "content": "지시를 지금 실행하세요."},
    ]
    model = llm.selected_model(owner)
    answer = ""
    for _round in range(MAX_ROUNDS):
        result = llm.complete(messages, TOOLS, model=model)
        if not result["tool_calls"]:
            answer = result["content"].strip()
            break
        turn: dict[str, Any] = {
            "role": "assistant",
            "content": result["content"],
            "tool_calls": result["tool_calls"],
        }
        if result.get("replay"):
            turn["replay"] = result["replay"]
        messages.append(turn)
        for call in result["tool_calls"]:
            try:
                output = _dispatch(
                    bot,
                    owner,
                    call["name"],
                    call["arguments"],
                    defer=defer,
                    pending=pending,
                    record_ids=record_ids,
                )
            except HttpError as exc:
                output = {"error": exc.message}
            except (KeyError, TypeError, ValueError):
                output = {"error": "도구 인자가 올바르지 않습니다."}
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": _dump(output)}
            )
    else:
        raise HttpError(500, "지시를 정해진 단계 안에 마치지 못했습니다.")
    return {
        "summary": answer or "지시를 실행했습니다.",
        "record_ids": list(dict.fromkeys(record_ids)),
        "pending": pending,
    }


def apply_pending(bot: Workbot, owner, pending: list[dict[str, Any]]) -> list[int]:
    """확인 대기 중이던 쓰기 작업을 실제로 반영합니다."""
    record_ids: list[int] = []
    for item in pending:
        if item.get("kind") == "create_record":
            database = _database(bot, owner, str(item["database_slug"]))
            saved = create_record(
                owner,
                database.id,
                {
                    "title": item["title"],
                    "values": item.get("values") or {},
                    "blocks": item.get("blocks") or [],
                },
                RecordActivity.Source.AGENT,
            )
            record_ids.append(saved["id"])
        elif item.get("kind") == "update_record":
            data = {key: item[key] for key in ("title", "values", "blocks") if key in item}
            saved = update_record(owner, int(item["record_id"]), data, RecordActivity.Source.AGENT)
            record_ids.append(saved["id"])
    return list(dict.fromkeys(record_ids))
