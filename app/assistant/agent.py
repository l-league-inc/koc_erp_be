import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from ninja.errors import HttpError

from assistant import llm, skillbook
from assistant.web_search import TOOL as _WEB_SEARCH_TOOL
from assistant.web_search import search_web
from assistant.models import AgentMessage, AgentSession, ProposedAction
from estimate.calculate import calculate
from estimate.compose import draft_from_payload
from estimate.errors import EstimateError
from estimate.schema import EstimateDraft
from estimate.service import document_payload
from workspace.models import Property, Record, RecordActivity
from document.utils import get_file_detail, search_files
from mail import service as mail_service
from workspace.utils import (
    accessible_databases,
    create_record,
    fold_date_range_aliases,
    get_membership,
    get_record,
    list_members,
    query_records,
    serialize_database,
    update_record,
)

_MAX_ROUNDS = 8
_IMMEDIATE_RECORD_SLUGS = frozenset({"attendance"})
_SELF_CLOCK_IN = re.compile(
    r"^(?:오늘\s+)?출근(?:\s+(?:등록|체크))?(?:\s*해\s*(?:줘|주세요))?$"
)
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
            "name": "find_self_employee",
            "description": (
                "로그인한 사용자의 임직원 레코드를 찾습니다. "
                "사내 이메일이 계정 이메일과 같으면 그 행을 쓰고, 없으면 계정 이름과 제목이 같은 행을 씁니다. "
                "다른 사람을 지목하지 않은 출근은 이 도구로 본인을 정합니다."
            ),
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
            "description": (
                "레코드 생성 초안을 만듭니다. 사용자가 확정하기 전에는 저장하지 않습니다. "
                "database_slug가 attendance이면 초안 없이 바로 저장하고 confirmed로 돌려줍니다."
            ),
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
            "description": (
                "이미 저장된 레코드의 수정 초안을 만듭니다. 사용자가 확정하기 전에는 저장하지 않습니다. "
                "출근(attendance) 레코드는 바로 저장하고 confirmed로 돌려줍니다. "
                "record_id가 없는 대기 초안은 이 도구가 아니라 revise_pending_action을 씁니다."
            ),
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
    {
        "type": "function",
        "function": {
            "name": "revise_pending_action",
            "description": (
                "아직 확정하지 않은 레코드 초안의 제목·값·본문을 고칩니다. "
                "대기 중인 생성 초안에는 record_id가 없으므로 초안 id를 action_id로 넘깁니다. "
                "새 초안을 만들지 않고, 저장은 사용자가 확정한 뒤에 됩니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "values": {"type": "object"},
                    "blocks": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["action_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "사용 가능한 스킬의 이름과 설명만 조회합니다. 본문은 포함하지 않습니다.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_skill",
            "description": "스킬 전문을 읽습니다. 설명과 맞는 일을 하기 전에 호출합니다.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_skill",
            "description": "워크스페이스 스킬 생성 초안을 만듭니다. 사용자가 확정하기 전에는 저장하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["name", "description", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_estimate",
            "description": "견적서 파일 초안을 만듭니다. 금액은 계산하지 않습니다. 사용자가 확정하기 전에는 파일이 없습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client": {"type": "string"},
                    "department": {"type": "string"},
                    "contact": {"type": "string"},
                    "issued_on": {"type": "string"},
                    "product_name": {"type": "string"},
                    "devices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "serial": {"type": "string"},
                                "part_name": {"type": "string"},
                                "part_unit": {"type": "string"},
                                "part_qty": {"type": "integer"},
                                "part_unit_price": {"type": "integer"},
                                "labor_level": {"type": "string"},
                                "labor_hours": {"type": "integer"},
                                "labor_unit_price": {"type": "integer"},
                            },
                            "required": [
                                "serial",
                                "part_name",
                                "part_qty",
                                "part_unit_price",
                                "labor_level",
                                "labor_hours",
                                "labor_unit_price",
                            ],
                        },
                    },
                    "shipping_qty": {"type": "integer"},
                    "shipping_unit_price": {"type": "integer"},
                },
                "required": [
                    "client",
                    "department",
                    "contact",
                    "issued_on",
                    "product_name",
                    "devices",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_skill",
            "description": "워크스페이스 스킬 수정 초안을 만듭니다. 고정 스킬은 수정할 수 없습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "공유 문서함과 내 개인 문서함에서 파일을 검색합니다. 다른 사람의 개인 문서는 나오지 않습니다. "
                "kind는 image, audio, video 중 하나이고 없으면 전체입니다. "
                "결과에는 content_type, space_kind, media_kind, tags_ko, index_status, description_ko가 있습니다. "
                "공유 문서함 이미지는 장면 설명, 오디오는 앞 180초 전사, 영상은 장면 설명이 상세 extracted_text에 있습니다. "
                "영상 요약은 첫 장면만입니다. 개인 문서함 미디어는 본문이 비어 있습니다. "
                "다운로드 URL은 내용을 대신 읽지 못합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "kind": {"type": "string", "enum": ["image", "audio", "video"]},
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": (
                "문서 메타, 요약, 추출 본문을 조회합니다. 업로드나 삭제는 하지 않습니다. "
                "공유 문서함 이미지는 장면 설명, 오디오는 앞 180초 전사, 영상은 장면 설명이 extracted_text에 있습니다. "
                "영상 요약은 첫 장면만입니다. 개인 문서함 미디어는 본문이 비어 있습니다. "
                "다운로드 URL은 내용을 대신 읽지 못합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {"file_id": {"type": "integer"}},
                "required": ["file_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mails",
            "description": "연결된 Daum 메일 목록을 조회합니다. 저장하거나 발송하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "limit": {"type": "integer"},
                    "unread_only": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mail",
            "description": "메일 본문을 조회합니다. 저장하거나 발송하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string"},
                    "folder": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_send_mail",
            "description": "메일 발송 초안을 만듭니다. 사용자가 확정하기 전에는 발송하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    _WEB_SEARCH_TOOL,
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
        "updated_at": session.updated_at,
    }


def _preview(content: str) -> str:
    text = " ".join((content or "").split())
    if len(text) <= 80:
        return text
    return text[:80] + "…"


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


def _related_slugs(user, session: AgentSession) -> set[str]:
    if not session.database_slug:
        return set()
    database = _database(user, session.workspace_id, session.database_slug)
    target_ids: list[int] = []
    for prop in database.properties.filter(type=Property.Type.RELATION):
        raw = (prop.config or {}).get("database_id")
        if isinstance(raw, int) and not isinstance(raw, bool):
            target_ids.append(raw)
    if not target_ids:
        return set()
    return set(
        accessible_databases(user)
        .filter(workspace_id=session.workspace_id, id__in=target_ids)
        .values_list("slug", flat=True)
    )


def _read_slug(user, session: AgentSession, requested: str) -> str:
    cleaned = (requested or "").strip()
    if not session.database_slug or not cleaned or cleaned == session.database_slug:
        return cleaned or session.database_slug
    if cleaned in _related_slugs(user, session):
        return cleaned
    raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")


def list_sessions(user, workspace_id: int | None) -> list[dict[str, Any]]:
    sessions = AgentSession.objects.filter(user=user)
    if workspace_id is not None:
        get_membership(user, workspace_id)
        sessions = sessions.filter(workspace_id=workspace_id)
    last_content = (
        AgentMessage.objects.filter(session=OuterRef("pk")).order_by("-id").values("content")[:1]
    )
    rows = sessions.annotate(last_content=Subquery(last_content)).order_by("-updated_at", "-id")[:50]
    payload = []
    for session in rows:
        item = serialize_session(session)
        item["preview"] = _preview(session.last_content or "")
        payload.append(item)
    return payload


def get_session_detail(user, session_id: int) -> dict[str, Any]:
    session = _session(user, session_id)
    detail = serialize_session(session)
    detail["messages"] = [
        serialize_message(message) for message in session.messages.order_by("id")
    ]
    detail["proposed_actions"] = [
        serialize_action(action) for action in session.proposed_actions.order_by("id")
    ]
    return detail


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


def delete_session(user, session_id: int) -> None:
    session = _session(user, session_id)
    session.delete()


def _prepare_values(database, values: dict[str, Any]) -> dict[str, Any]:
    folded = fold_date_range_aliases(database, values)
    known = set(database.properties.values_list("slug", flat=True))
    unknown = [slug for slug in folded if slug not in known]
    if unknown:
        allowed = ", ".join(sorted(known))
        raise HttpError(
            400,
            f"속성 {unknown[0]}을 찾을 수 없습니다. 쓸 수 있는 속성은 {allowed}입니다.",
        )
    return folded


def _history(session: AgentSession) -> list[dict[str, str]]:
    messages = list(session.messages.order_by("-id")[:20])
    messages.reverse()
    return [{"role": message.role, "content": message.content} for message in messages]


_LEDGER_LIMIT = 30


def _action_label(action: ProposedAction) -> str:
    payload = action.payload or {}
    result = action.result or {}
    parts: list[str] = []
    if action.kind in {ProposedAction.Kind.CREATE_RECORD, ProposedAction.Kind.UPDATE_RECORD}:
        title = _preview(str(payload.get("title") or ""))
        record_id = result.get("record_id") or payload.get("record_id")
        slug = str(payload.get("database_slug") or "")
        if slug:
            parts.append(f"database_slug {slug}")
        if title:
            parts.append(f"제목 {title}")
        if record_id:
            parts.append(f"record_id {record_id}")
    elif action.kind in {ProposedAction.Kind.CREATE_SKILL, ProposedAction.Kind.UPDATE_SKILL}:
        name = _preview(str(payload.get("name") or result.get("name") or ""))
        if name:
            parts.append(f"이름 {name}")
        if result.get("skill_id"):
            parts.append(f"skill_id {result['skill_id']}")
    elif action.kind == ProposedAction.Kind.SEND_MAIL:
        subject = _preview(str(payload.get("subject") or ""))
        if subject:
            parts.append(f"제목 {subject}")
    elif action.kind == ProposedAction.Kind.CREATE_ESTIMATE:
        client = _preview(str(payload.get("client") or ""))
        filename = _preview(str(result.get("filename") or ""))
        if client:
            parts.append(f"거래처 {client}")
        if filename:
            parts.append(f"파일 {filename}")
    return " ".join(parts)


def _action_ledger(session: AgentSession) -> str:
    actions = list(session.proposed_actions.order_by("-id")[: _LEDGER_LIMIT + 1])
    hidden = len(actions) > _LEDGER_LIMIT
    actions = list(reversed(actions[:_LEDGER_LIMIT]))
    if not actions:
        return "이 대화의 초안은 없습니다."
    lines = ["이 대화의 초안 상태입니다."]
    if hidden:
        lines.append(f"최근 {_LEDGER_LIMIT}건만 표시합니다.")
    for action in actions:
        label = _action_label(action)
        suffix = f" {label}" if label else ""
        lines.append(f"- id {action.id} {action.kind} {action.status}{suffix}")
    lines.append(
        "pending은 아직 반영 전입니다. 같은 내용의 초안을 다시 만들지 않습니다. "
        "pending 생성 초안에는 record_id가 없습니다. 내용을 고칠 때는 적힌 id로 revise_pending_action을 한 번 호출합니다. "
        "confirmed는 사용자가 확정하여 이미 반영되었습니다. "
        "확정된 레코드를 고칠 때는 적힌 record_id로 propose_update_record를 한 번 호출합니다. "
        "confirmed 메일은 다시 propose_send_mail하지 않습니다. "
        "confirmed 견적서는 파일이 만들어진 상태입니다."
    )
    return "\n".join(lines)


def _confirm_notice(
    records: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    mails: list[dict[str, Any]],
    estimates: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    for item in records:
        parts.append(f"레코드 {item['record_id']} {item['title']}")
    for item in skills:
        parts.append(f"스킬 {item['name']}")
    for item in mails:
        parts.append(f"메일 {item['subject']}")
    for item in estimates:
        parts.append(f"견적서 {item['filename']}")
    return "확정되어 반영되었습니다. " + ", ".join(parts) + "."


def _immediate_saved_notice(action_ids: list[int]) -> str:
    if not action_ids:
        return ""
    records: list[dict[str, Any]] = []
    actions = ProposedAction.objects.filter(id__in=action_ids).order_by("id")
    for action in actions:
        payload = action.payload or {}
        if payload.get("database_slug") not in _IMMEDIATE_RECORD_SLUGS:
            continue
        if action.status != ProposedAction.Status.CONFIRMED:
            continue
        record_id = (action.result or {}).get("record_id")
        if not record_id:
            continue
        title = str(payload.get("title") or "")
        if not title:
            title = Record.objects.filter(id=record_id).values_list("title", flat=True).first() or ""
        records.append({"record_id": record_id, "title": title})
    if not records:
        return ""
    return _confirm_notice(records, [], [], [])


def _pending_draft_notice(action_ids: list[int]) -> str:
    if not action_ids:
        return ""
    parts: list[str] = []
    actions = ProposedAction.objects.filter(id__in=action_ids).order_by("id")
    for action in actions:
        if action.status != ProposedAction.Status.PENDING:
            continue
        if action.kind not in {
            ProposedAction.Kind.CREATE_RECORD,
            ProposedAction.Kind.UPDATE_RECORD,
        }:
            continue
        payload = action.payload or {}
        title = _preview(str(payload.get("title") or ""))
        label = f"초안 {action.id}"
        if title:
            label = f"{label} {title}"
        parts.append(label)
    if not parts:
        return ""
    return "내용을 초안에 반영했습니다. 확정하기 전에는 저장되지 않습니다. " + ", ".join(parts) + "."


def _system_prompt(session: AgentSession, user) -> str:
    scope = session.database_slug or "전체"
    index = skillbook.active_index(session.workspace_id)
    lines = [f"- {item['name']}: {item['description']}" for item in index]
    catalog = "\n".join(lines) if lines else "- 없음"
    return (
        "당신은 KOC 워크스페이스 업무 도우미입니다. "
        "사용자에게 보이는 문장은 한국어로만 작성합니다. "
        f"워크스페이스 id는 {session.workspace_id}이고 범위는 {scope}입니다. "
        f"오늘 날짜는 {timezone.now().date().isoformat()}이고 "
        f"사용자 id는 {user.id}이며 {_user_identity(user)} "
        "다른 사람을 지목하지 않은 출근은 find_self_employee로 본인을 정하고 바로 저장합니다. "
        "그 경우 이름을 묻지 않습니다. "
        "멤버, 스키마, 레코드는 도구로 조회합니다. "
        "values의 키는 get_database_schema에 있는 slug만 사용합니다. "
        "날짜 범위는 그 date 속성에 {\"start\",\"end\"}로 넣습니다. "
        "스키마에 없는 start_date나 end_date는 넣지 않습니다. "
        "페이지 데이터베이스의 임직원 칸은 employees 레코드 id 배열입니다. "
        "people 속성에만 list_members의 user_id를 사용합니다. "
        "아래는 스킬 이름과 설명입니다. 본문은 포함되어 있지 않습니다. "
        "사용자 문장이 설명과 맞으면 view_skill로 전문을 읽고 그 절차를 따릅니다. "
        "레코드나 스킬을 만들거나 고칠 때는 propose 도구만 사용합니다. "
        "pending 초안은 아직 반영 전입니다. "
        "출근(attendance) 생성·수정은 propose 직후 서버가 저장하고 confirmed와 record_id를 돌려줍니다. "
        "그 응답을 보면 이미 반영된 것이니 확정 전이라거나 반영할 수 없다고 말하지 않습니다. "
        "휴가처럼 바로 저장하지 않는 생성 초안은 pending이고 record_id가 없습니다. "
        "그 초안의 내용을 고칠 때는 초안 id로 revise_pending_action을 한 번만 호출합니다. "
        "그때는 레코드를 조회하거나 propose_update_record를 쓰지 않습니다. "
        "confirmed에 record_id가 있을 때만 propose_update_record를 한 번 호출합니다. "
        "초안을 만들거나 고친 뒤에는 도구를 멈추고, 확정 전에는 저장되지 않았다고 안내합니다. "
        "confirmed로 적힌 항목은 이미 반영된 사실이니 그 내용을 다시 propose하지 않습니다. "
        "회사 밖 사실(정부지원사업, 공고, 뉴스, 법령)은 web_search로 확인하고 출처 URL을 함께 안내합니다. "
        "검색하지 않은 내용을 지어내지 않습니다. "
        "회사 문서는 search_documents로 찾고 get_document의 extracted_text로 본문을 읽습니다. "
        "이미지, 음성, 영상은 kind와 media_kind로 고릅니다. "
        "개인 문서는 이 사용자 것만 나옵니다. "
        "메일은 list_mails와 get_mail로 읽고, 보낼 때는 propose_send_mail만 씁니다. "
        "pending 메일은 발송 전입니다. confirmed 메일은 이미 발송되었습니다. "
        "견적서 파일은 propose_create_estimate만 씁니다. 행 금액과 합계는 넣지 않습니다. "
        "확정 결과는 미리보기이며, PDF를 받았거나 메일을 보냈다고 말하지 않습니다.\n"
        f"{catalog}\n\n"
        f"{_action_ledger(session)}"
    )


def _user_identity(user) -> str:
    name = str(user.name or "").strip()
    if name:
        return f"이름은 {name}이고 이메일은 {user.email}입니다."
    return f"이름은 비어 있고 이메일은 {user.email}입니다."


def _employee_matches(user, workspace_id: int, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        result = query_records(
            user,
            {
                "workspace_id": workspace_id,
                "database_slug": "employees",
                "filters": filters,
                "page": 1,
                "page_size": 20,
            },
        )
    except HttpError:
        return []
    return list(result.get("data") or [])


def find_self_employee(user, workspace_id: int) -> dict[str, Any]:
    """계정 이메일과 같은 임직원을 먼저 찾고, 없으면 계정 이름과 제목이 같은 행을 찾습니다."""
    email = str(user.email or "").strip()
    name = str(user.name or "").strip()
    matches: list[dict[str, Any]] = []
    if email:
        matches = _employee_matches(
            user,
            workspace_id,
            [{"property": "email", "op": "eq", "value": email}],
        )
    if not matches and name:
        matches = _employee_matches(
            user,
            workspace_id,
            [{"property": "title", "op": "eq", "value": name}],
        )
    cards = [{"id": row["id"], "title": row["title"]} for row in matches]
    if len(cards) == 1:
        return {"found": True, "id": cards[0]["id"], "title": cards[0]["title"]}
    return {"found": False, "matches": cards}


def _is_self_clock_in(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", text.strip())
    return _SELF_CLOCK_IN.match(cleaned) is not None


def _attendance_database(user, workspace_id: int):
    return (
        accessible_databases(user).filter(workspace_id=workspace_id, slug="attendance").first()
    )


def _today_attendance(user, workspace_id: int, employee_id: int) -> dict[str, Any] | None:
    today = timezone.now().date().isoformat()
    rows = []
    try:
        result = query_records(
            user,
            {
                "workspace_id": workspace_id,
                "database_slug": "attendance",
                "filters": [
                    {"property": "employee", "op": "eq", "value": employee_id},
                    {"property": "work_date", "op": "eq", "value": today},
                ],
                "page": 1,
                "page_size": 1,
            },
        )
        rows = list(result.get("data") or [])
    except HttpError:
        return None
    if not rows:
        return None
    return rows[0]


def _clock_in_self(user, session: AgentSession, text: str) -> dict[str, Any] | None:
    if session.database_slug and session.database_slug != "attendance":
        return None
    if not _is_self_clock_in(text):
        return None
    database = _attendance_database(user, session.workspace_id)
    if database is None:
        return None
    slugs = set(database.properties.values_list("slug", flat=True))
    if "employee" not in slugs:
        return None
    employee = find_self_employee(user, session.workspace_id)
    if not employee["found"]:
        return None
    existing = _today_attendance(user, session.workspace_id, int(employee["id"]))
    if existing is not None:
        title = str(existing.get("title") or "")
        answer = f"오늘 출근은 이미 있습니다. 레코드 {existing['id']} {title}."
        return _reply(session, answer, [])
    moment = timezone.now()
    if timezone.is_aware(moment):
        moment = timezone.make_naive(moment)
    moment = moment.replace(microsecond=0)
    today = moment.date().isoformat()
    values: dict[str, Any] = {"employee": [employee["id"]]}
    if "work_date" in slugs:
        values["work_date"] = today
    if "check_in" in slugs:
        values["check_in"] = moment.isoformat()
    created: list[int] = []
    with transaction.atomic():
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.CREATE_RECORD,
            payload={
                "database_slug": "attendance",
                "title": f"{today} 출근",
                "values": values,
                "blocks": [],
            },
        )
        _confirm_immediate_record(user, session, action)
        created.append(action.id)
    return _reply(session, _immediate_saved_notice(created), created)


def _reply(session: AgentSession, answer: str, created: list[int]) -> dict[str, Any]:
    message = AgentMessage.objects.create(
        session=session,
        role=AgentMessage.Role.ASSISTANT,
        content=answer,
    )
    session.save(update_fields=["updated_at"])
    actions = ProposedAction.objects.filter(id__in=created).order_by("id")
    return {
        "message": serialize_message(message),
        "proposed_actions": [serialize_action(action) for action in actions],
    }


def _pending_record_action(session: AgentSession, action_id: int) -> ProposedAction | None:
    return ProposedAction.objects.filter(
        session=session,
        id=action_id,
        status=ProposedAction.Status.PENDING,
        kind__in=[
            ProposedAction.Kind.CREATE_RECORD,
            ProposedAction.Kind.UPDATE_RECORD,
        ],
    ).first()


def _revise_pending(
    session: AgentSession,
    user,
    arguments: dict[str, Any],
    created: list[int],
) -> dict[str, Any]:
    raw_id = arguments.get("action_id")
    if raw_id is None:
        raise HttpError(400, "초안 id가 필요합니다.")
    action = _pending_record_action(session, int(raw_id))
    if action is None:
        raise HttpError(
            404,
            "대기 중인 초안을 찾을 수 없습니다. 확정된 레코드는 record_id로 propose_update_record를 사용합니다.",
        )
    payload = dict(action.payload or {})
    if action.kind == ProposedAction.Kind.CREATE_RECORD:
        slug = str(payload.get("database_slug") or "")
        if session.database_slug and slug != session.database_slug:
            raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")
        database = _database(user, session.workspace_id, slug)
    else:
        record = get_record(user, int(payload["record_id"]))
        if record.database.workspace_id != session.workspace_id:
            raise HttpError(404, "레코드를 찾을 수 없습니다.")
        if session.database_slug and record.database.slug != session.database_slug:
            raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")
        database = record.database
    has_title = arguments.get("title") is not None
    has_blocks = arguments.get("blocks") is not None
    raw_values = arguments.get("values")
    if raw_values is not None and not isinstance(raw_values, dict):
        raise HttpError(400, "값은 객체여야 합니다.")
    has_values = isinstance(raw_values, dict) and bool(raw_values)
    if not has_title and not has_values and not has_blocks:
        raise HttpError(400, "수정할 내용이 필요합니다.")
    if has_title:
        title = str(arguments["title"]).strip()
        if action.kind == ProposedAction.Kind.CREATE_RECORD and not title:
            raise HttpError(400, "제목이 필요합니다.")
        payload["title"] = title
    if has_values:
        merged = dict(payload.get("values") or {})
        merged.update(_prepare_values(database, raw_values))
        payload["values"] = merged
    if has_blocks:
        if not isinstance(arguments["blocks"], list):
            raise HttpError(400, "본문 블록은 배열이어야 합니다.")
        payload["blocks"] = arguments["blocks"]
    action.payload = payload
    action.save(update_fields=["payload", "updated_at"])
    if action.id not in created:
        created.append(action.id)
    return serialize_action(action)


def _dispatch(session: AgentSession, user, name: str, arguments: dict[str, Any], created: list[int]) -> Any:
    if name == "list_members":
        return list_members(user, session.workspace_id)
    if name == "find_self_employee":
        return find_self_employee(user, session.workspace_id)
    if name == "list_databases":
        databases = accessible_databases(user).filter(workspace_id=session.workspace_id)
        if session.database_slug:
            databases = databases.filter(
                slug__in={session.database_slug, *_related_slugs(user, session)}
            )
        return [serialize_database(database) for database in databases.order_by("position", "id")]
    if name == "get_database_schema":
        slug = _read_slug(user, session, str(arguments.get("database_slug") or ""))
        if not slug:
            raise HttpError(400, "영역 slug가 필요합니다.")
        return serialize_database(_database(user, session.workspace_id, slug), detail=True)
    if name == "query_records":
        slug = _read_slug(user, session, str(arguments.get("database_slug") or ""))
        filters = arguments.get("filters") or []
        keyword = str(arguments.get("q") or "")
        if slug:
            return query_records(
                user,
                {"database_slug": slug, "filters": filters, "q": keyword, "page": 1, "page_size": 20},
            )
        return query_records(
            user,
            {
                "workspace_id": session.workspace_id,
                "filters": filters,
                "q": keyword,
                "page": 1,
                "page_size": 20,
            },
        )
    if name == "propose_create_record":
        slug = _scoped_slug(session, str(arguments.get("database_slug") or ""))
        title = str(arguments.get("title") or "").strip()
        if not slug or not title:
            raise HttpError(400, "영역과 제목이 필요합니다.")
        database = _database(user, session.workspace_id, slug)
        values = arguments.get("values") or {}
        blocks = arguments.get("blocks") or []
        if not isinstance(values, dict) or not isinstance(blocks, list):
            raise HttpError(400, "값 형식이 올바르지 않습니다.")
        values = _prepare_values(database, values)
        with transaction.atomic():
            action = ProposedAction.objects.create(
                session=session,
                kind=ProposedAction.Kind.CREATE_RECORD,
                payload={"database_slug": slug, "title": title, "values": values, "blocks": blocks},
            )
            _confirm_immediate_record(user, session, action)
        created.append(action.id)
        return serialize_action(action)
    if name == "propose_update_record":
        raw_id = arguments.get("record_id")
        if raw_id is None:
            raise HttpError(400, "레코드가 필요합니다.")
        record_id = int(raw_id)
        pending = _pending_record_action(session, record_id)
        if pending is not None and not Record.objects.filter(id=record_id).exists():
            revised = dict(arguments)
            revised["action_id"] = pending.id
            return _revise_pending(session, user, revised, created)
        record = get_record(user, record_id)
        if record.database.workspace_id != session.workspace_id:
            raise HttpError(404, "레코드를 찾을 수 없습니다.")
        if session.database_slug and record.database.slug != session.database_slug:
            raise HttpError(400, "이 대화는 선택한 영역만 다룹니다.")
        payload: dict[str, Any] = {
            "record_id": record.id,
            "database_slug": record.database.slug,
        }
        if arguments.get("title") is not None:
            payload["title"] = str(arguments["title"])
        if arguments.get("values") is not None:
            if not isinstance(arguments["values"], dict):
                raise HttpError(400, "값은 객체여야 합니다.")
            payload["values"] = _prepare_values(record.database, arguments["values"])
        if arguments.get("blocks") is not None:
            if not isinstance(arguments["blocks"], list):
                raise HttpError(400, "본문 블록은 배열이어야 합니다.")
            payload["blocks"] = arguments["blocks"]
        with transaction.atomic():
            action = ProposedAction.objects.create(
                session=session,
                kind=ProposedAction.Kind.UPDATE_RECORD,
                payload=payload,
            )
            _confirm_immediate_record(user, session, action)
        created.append(action.id)
        return serialize_action(action)
    if name == "revise_pending_action":
        return _revise_pending(session, user, arguments, created)
    if name == "list_skills":
        return skillbook.active_index(session.workspace_id)
    if name == "view_skill":
        return skillbook.view_skill(session.workspace_id, str(arguments.get("name") or ""))
    if name == "propose_create_skill":
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.CREATE_SKILL,
            payload=skillbook.prepare_create_payload(session.workspace_id, arguments),
        )
        created.append(action.id)
        return serialize_action(action)
    if name == "web_search":
        return search_web(
            str(arguments.get("query") or ""),
            max_results=arguments.get("max_results"),
            time_range=arguments.get("time_range"),
            include_domains=arguments.get("include_domains"),
            topic=arguments.get("topic"),
        )
    if name == "search_documents":
        return search_files(
            user,
            session.workspace_id,
            str(arguments.get("q") or ""),
            str(arguments.get("kind") or ""),
        )
    if name == "get_document":
        return get_file_detail(user, session.workspace_id, int(arguments["file_id"]))
    if name == "list_mails":
        limit = arguments.get("limit")
        return mail_service.list_messages(
            user,
            folder=str(arguments.get("folder") or "INBOX"),
            limit=int(limit) if limit is not None else 20,
            unread_only=bool(arguments.get("unread_only")),
        )
    if name == "get_mail":
        uid = str(arguments.get("uid") or "").strip()
        if not uid:
            raise HttpError(400, "메일 uid가 필요합니다.")
        return mail_service.get_message(
            user,
            uid,
            folder=str(arguments.get("folder") or "INBOX"),
        )
    if name == "propose_send_mail":
        to_raw = arguments.get("to") or []
        if not isinstance(to_raw, list) or not to_raw:
            raise HttpError(400, "받는 사람이 필요합니다.")
        to_list = [str(item).strip() for item in to_raw if str(item).strip()]
        if not to_list:
            raise HttpError(400, "받는 사람이 필요합니다.")
        subject = str(arguments.get("subject") or "").strip()
        body = str(arguments.get("body") or "")
        if not subject:
            raise HttpError(400, "제목이 필요합니다.")
        mail_payload: dict[str, Any] = {
            "to": to_list,
            "subject": subject,
            "body": body,
        }
        if arguments.get("cc") is not None:
            if not isinstance(arguments["cc"], list):
                raise HttpError(400, "cc는 배열이어야 합니다.")
            mail_payload["cc"] = [
                str(item).strip() for item in arguments["cc"] if str(item).strip()
            ]
        if arguments.get("bcc") is not None:
            if not isinstance(arguments["bcc"], list):
                raise HttpError(400, "bcc는 배열이어야 합니다.")
            mail_payload["bcc"] = [
                str(item).strip() for item in arguments["bcc"] if str(item).strip()
            ]
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.SEND_MAIL,
            payload=mail_payload,
        )
        created.append(action.id)
        return serialize_action(action)
    if name == "propose_create_estimate":
        try:
            draft = draft_from_payload(arguments)
            calculate(draft)
        except EstimateError as exc:
            raise HttpError(400, str(exc)) from None
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.CREATE_ESTIMATE,
            payload=draft.model_dump(mode="json"),
        )
        created.append(action.id)
        return serialize_action(action)
    if name == "propose_update_skill":
        action = ProposedAction.objects.create(
            session=session,
            kind=ProposedAction.Kind.UPDATE_SKILL,
            payload=skillbook.prepare_update_payload(session.workspace_id, arguments),
        )
        created.append(action.id)
        return serialize_action(action)
    raise HttpError(400, "지원하지 않는 도구입니다.")


def send_message(user, session_id: int, content: str, model: str = "") -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise HttpError(400, "내용이 필요합니다.")
    if len(text) > 4000:
        raise HttpError(400, "내용은 4000자를 넘길 수 없습니다.")
    session = _session(user, session_id)
    AgentMessage.objects.create(session=session, role=AgentMessage.Role.USER, content=text)
    clocked = _clock_in_self(user, session, text)
    if clocked is not None:
        return clocked
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(session, user)},
        *_history(session),
    ]
    created: list[int] = []
    answer = ""
    chosen = llm.use_model(user, model)
    for _round in range(_MAX_ROUNDS):
        result = llm.complete(messages, _TOOLS, model=chosen)
        if not result["tool_calls"]:
            answer = result["content"].strip() or "요청을 확인했습니다."
            break
        turn = {
            "role": "assistant",
            "content": result["content"],
            "tool_calls": result["tool_calls"],
        }
        if result.get("replay"):
            turn["replay"] = result["replay"]
        messages.append(turn)
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
        answer = _pending_draft_notice(created) or "요청을 마치지 못했습니다. 다시 말해 주세요."
    saved_notice = _immediate_saved_notice(created)
    if saved_notice:
        answer = saved_notice
    return _reply(session, answer, created)


def _apply_proposed_action(user, session: AgentSession, action: ProposedAction) -> tuple[str, dict[str, Any]]:
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
        action.result = {"record_id": saved["id"]}
        bucket = "records"
        item = {
            "action_id": action.id,
            "record_id": saved["id"],
            "database_id": saved["database_id"],
            "title": saved["title"],
        }
    elif action.kind == ProposedAction.Kind.UPDATE_RECORD:
        update_data: dict[str, Any] = {
            "title": payload.get("title"),
            "values": payload.get("values"),
        }
        if "blocks" in payload:
            update_data["blocks"] = payload.get("blocks") or []
        saved = update_record(
            user,
            int(payload["record_id"]),
            update_data,
            RecordActivity.Source.AGENT,
        )
        action.result = {"record_id": saved["id"]}
        bucket = "records"
        item = {
            "action_id": action.id,
            "record_id": saved["id"],
            "database_id": saved["database_id"],
            "title": saved["title"],
        }
    elif action.kind in {
        ProposedAction.Kind.CREATE_SKILL,
        ProposedAction.Kind.UPDATE_SKILL,
    }:
        saved = skillbook.apply_skill_proposal(user, session.workspace_id, action.kind, payload)
        action.result = {"skill_id": saved["id"], "name": saved["name"]}
        bucket = "skills"
        item = {"action_id": action.id, "skill_id": saved["id"], "name": saved["name"]}
    elif action.kind == ProposedAction.Kind.CREATE_ESTIMATE:
        try:
            document = document_payload(EstimateDraft.model_validate(payload))
        except EstimateError as exc:
            raise HttpError(400, str(exc)) from None
        action.result = document
        bucket = "estimates"
        item = {"action_id": action.id, **document}
    elif action.kind == ProposedAction.Kind.SEND_MAIL:
        sent = mail_service.send_message(
            user,
            to=list(payload.get("to") or []),
            subject=str(payload.get("subject") or ""),
            body=str(payload.get("body") or ""),
            cc=list(payload.get("cc") or []),
            bcc=list(payload.get("bcc") or []),
        )
        action.result = sent
        bucket = "mails"
        item = {"action_id": action.id, **sent}
    else:
        raise HttpError(400, "지원하지 않는 초안입니다.")
    action.status = ProposedAction.Status.CONFIRMED
    action.save(update_fields=["status", "result", "updated_at"])
    return bucket, item


def _confirm_immediate_record(user, session: AgentSession, action: ProposedAction) -> None:
    if action.kind not in {
        ProposedAction.Kind.CREATE_RECORD,
        ProposedAction.Kind.UPDATE_RECORD,
    }:
        return
    if (action.payload or {}).get("database_slug") not in _IMMEDIATE_RECORD_SLUGS:
        return
    _apply_proposed_action(user, session, action)


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
    skills = []
    mails = []
    estimates = []
    buckets = {
        "records": records,
        "skills": skills,
        "mails": mails,
        "estimates": estimates,
    }
    for action in actions:
        bucket, item = _apply_proposed_action(user, session, action)
        buckets[bucket].append(item)
    notice = AgentMessage.objects.create(
        session=session,
        role=AgentMessage.Role.ASSISTANT,
        content=_confirm_notice(records, skills, mails, estimates),
    )
    session.save(update_fields=["updated_at"])
    return {
        "message": serialize_message(notice),
        "proposed_actions": [serialize_action(action) for action in actions],
        "records": records,
        "skills": skills,
        "mails": mails,
        "estimates": estimates,
    }
