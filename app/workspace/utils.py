import re
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from ninja.errors import HttpError

from workspace.events import publish_collab_event, publish_workspace_event
from workspace.models import (
    Block,
    Database,
    DatabaseTemplate,
    Page,
    Property,
    PropertyValue,
    Record,
    RecordActivity,
    RecordComment,
    RelationLink,
    View,
    Workspace,
    WorkspaceMember,
)

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MCP_CLIENT_HEADER = "X-KOC-Client"
MAX_PAGE_SIZE = 100
TEXT_TYPES = {
    Property.Type.TITLE,
    Property.Type.TEXT,
    Property.Type.URL,
    Property.Type.EMAIL,
    Property.Type.PHONE,
}
OPTION_TYPES = {
    Property.Type.SELECT,
    Property.Type.STATUS,
    Property.Type.MULTI_SELECT,
}
FILTER_OPS = {"eq", "neq", "contains", "in", "gt", "gte", "lt", "lte", "is_empty"}
FILTER_GROUP_OPS = {"and", "or"}
SYSTEM_FIELDS = {"created_at", "updated_at", "created_by", "last_edited_by"}
SYSTEM_USER_FIELDS = {"created_by", "last_edited_by"}
SYSTEM_DATE_FIELDS = {"created_at", "updated_at"}
RICH_TEXT_ANNOTATIONS = {"bold", "italic", "strikethrough", "underline", "code", "color"}
BOOL_ANNOTATIONS = {"bold", "italic", "strikethrough", "underline", "code"}
TABLE_ALIGNS = {"Left", "Center", "Right"}
GROUP_PROPERTY_TYPES = {
    Property.Type.SELECT,
    Property.Type.STATUS,
    Property.Type.MULTI_SELECT,
}
COVER_PROPERTY_TYPES = {Property.Type.FILES, Property.Type.URL}
ACTIVITY_LIMIT = 50
TRASH_LIMIT = 100


def activity_source(request) -> str:
    if request.headers.get(MCP_CLIENT_HEADER) == RecordActivity.Source.MCP:
        return RecordActivity.Source.MCP
    return RecordActivity.Source.USER


def _section_slug(raw: Any) -> str:
    cleaned = str(raw or "").strip()
    if not cleaned:
        return ""
    return validate_slug(cleaned)


def validate_slug(slug: str) -> str:
    cleaned = (slug or "").strip()
    if not SLUG_PATTERN.match(cleaned):
        raise HttpError(400, "슬러그는 영문 소문자로 시작하고 숫자와 _만 쓸 수 있습니다.")
    return cleaned


def _membership_exists(user, workspace_id: int) -> bool:
    return WorkspaceMember.objects.filter(user=user, workspace_id=workspace_id).exists()


def get_membership(user, workspace_id: int) -> WorkspaceMember:
    membership = (
        WorkspaceMember.objects.select_related("workspace")
        .filter(user=user, workspace_id=workspace_id)
        .first()
    )
    if membership is not None:
        return membership
    if Workspace.objects.filter(id=workspace_id).exists():
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    raise HttpError(404, "워크스페이스를 찾을 수 없습니다.")


def get_database(user, database_id: int) -> Database:
    database = (
        Database.objects.select_related("workspace").filter(id=database_id).first()
    )
    if database is None:
        raise HttpError(404, "데이터베이스를 찾을 수 없습니다.")
    if not _membership_exists(user, database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return database


def get_record(user, record_id: int) -> Record:
    record = (
        Record.objects.select_related("database", "database__workspace")
        .filter(id=record_id)
        .first()
    )
    if record is None:
        raise HttpError(404, "레코드를 찾을 수 없습니다.")
    if not _membership_exists(user, record.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return record


def get_property(user, property_id: int) -> Property:
    prop = (
        Property.objects.select_related("database", "database__workspace")
        .filter(id=property_id)
        .first()
    )
    if prop is None:
        raise HttpError(404, "속성을 찾을 수 없습니다.")
    if not _membership_exists(user, prop.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return prop


def get_view(user, view_id: int) -> View:
    view = (
        View.objects.select_related("database", "database__workspace")
        .filter(id=view_id)
        .first()
    )
    if view is None:
        raise HttpError(404, "보기를 찾을 수 없습니다.")
    if not _membership_exists(user, view.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return view


def get_block(user, block_id: int) -> Block:
    block = (
        Block.objects.select_related(
            "record",
            "record__database",
            "record__database__workspace",
            "page",
            "page__workspace",
        )
        .filter(id=block_id)
        .first()
    )
    if block is None:
        raise HttpError(404, "블록을 찾을 수 없습니다.")
    workspace_id = (
        block.record.database.workspace_id if block.record_id else block.page.workspace_id
    )
    if not _membership_exists(user, workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return block


def accessible_databases(user) -> QuerySet[Database]:
    workspace_ids = WorkspaceMember.objects.filter(user=user).values("workspace_id")
    return Database.objects.filter(workspace_id__in=workspace_ids)


def list_members(user, workspace_id: int) -> list[dict[str, Any]]:
    get_membership(user, workspace_id)
    members = (
        WorkspaceMember.objects.filter(workspace_id=workspace_id)
        .select_related("user")
        .order_by("id")
    )
    return [
        {
            "user_id": member.user_id,
            "name": member.user.name or "",
            "role": member.role,
        }
        for member in members
    ]


def list_workspaces(user) -> list[Workspace]:
    memberships = WorkspaceMember.objects.filter(user=user).select_related("workspace")
    items: list[Workspace] = []
    for membership in memberships.order_by("workspace_id"):
        workspace = membership.workspace
        workspace.role = membership.role
        items.append(workspace)
    return items


def serialize_workspace(workspace: Workspace, role: str) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "role": role,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def serialize_property(prop: Property) -> dict[str, Any]:
    return {
        "id": prop.id,
        "database_id": prop.database_id,
        "name": prop.name,
        "slug": prop.slug,
        "type": prop.type,
        "config": prop.config or {},
        "position": prop.position,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
    }


def serialize_view(view: View) -> dict[str, Any]:
    return {
        "id": view.id,
        "database_id": view.database_id,
        "name": view.name,
        "type": view.type,
        "filters": view.filters or [],
        "sorts": view.sorts or [],
        "config": view.config or {},
        "position": view.position,
        "created_at": view.created_at,
        "updated_at": view.updated_at,
    }


def serialize_database(database: Database, *, detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": database.id,
        "workspace_id": database.workspace_id,
        "name": database.name,
        "slug": database.slug,
        "description": database.description,
        "icon": database.icon,
        "section": database.section,
        "section_slug": database.section_slug,
        "position": database.position,
        "access": database.access,
        "created_at": database.created_at,
        "updated_at": database.updated_at,
    }
    if detail:
        properties = database.properties.order_by("position", "id")
        views = database.views.order_by("position", "id")
        payload["properties"] = [serialize_property(prop) for prop in properties]
        payload["views"] = [serialize_view(view) for view in views]
    return payload


def serialize_block(block: Block) -> dict[str, Any]:
    return {
        "id": block.id,
        "record_id": block.record_id,
        "page_id": block.page_id,
        "parent_id": block.parent_id,
        "type": block.type,
        "content": block.content or {},
        "position": block.position,
        "created_at": block.created_at,
        "updated_at": block.updated_at,
    }


def collab_block_body(block: Block) -> dict[str, Any]:
    body = serialize_block(block)
    for key in ("created_at", "updated_at"):
        value = body[key]
        if hasattr(value, "isoformat"):
            body[key] = value.isoformat()
    return body


def emit_block_collab(block: Block, action: str, actor_id: int | None) -> None:
    target = "record" if block.record_id else "page"
    target_id = block.record_id or block.page_id
    body = None if action == "deleted" else collab_block_body(block)
    publish_collab_event(target, target_id, action, actor_id, block.id, body)


def export_value(stored: PropertyValue) -> Any:
    prop_type = stored.property.type
    if prop_type == Property.Type.NUMBER:
        if stored.number_value is None:
            return None
        return format(stored.number_value, "f").rstrip("0").rstrip(".") or "0"
    if prop_type == Property.Type.DATE:
        if stored.date_start is None:
            return None
        start = stored.date_start.isoformat()
        if stored.date_end is not None:
            return {"start": start, "end": stored.date_end.isoformat()}
        return start
    if prop_type == Property.Type.CHECKBOX:
        return bool(stored.checkbox_value)
    if prop_type in {
        Property.Type.MULTI_SELECT,
        Property.Type.PEOPLE,
        Property.Type.FILES,
        Property.Type.RELATION,
    }:
        return stored.json_value if stored.json_value is not None else []
    if prop_type in OPTION_TYPES:
        return stored.text_value
    return stored.text_value


def _relation_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [
        record_id
        for record_id in value
        if isinstance(record_id, int) and not isinstance(record_id, bool)
    ]


def _relation_cards(record_ids: list[int]) -> list[dict[str, Any]]:
    if not record_ids:
        return []
    rows = Record.objects.filter(id__in=record_ids).select_related("database")
    by_id = {row.id: row for row in rows}
    cards: list[dict[str, Any]] = []
    for record_id in record_ids:
        row = by_id.get(record_id)
        if row is None:
            continue
        cards.append(
            {
                "id": row.id,
                "title": row.title,
                "database_id": row.database_id,
                "database_slug": row.database.slug,
            }
        )
    return cards


def export_values(record: Record) -> dict[str, Any]:
    stored = (
        PropertyValue.objects.filter(record=record)
        .select_related("property")
        .order_by("property__position", "property_id")
    )
    values: dict[str, Any] = {}
    for item in stored:
        value = export_value(item)
        if item.property.type == Property.Type.RELATION:
            value = _relation_cards(_relation_ids(value))
        values[item.property.slug] = value
    return values


def _record_summary(record: Record, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.id,
        "database_id": record.database_id,
        "database_slug": record.database.slug,
        "database_name": record.database.name,
        "title": record.title,
        "icon": record.icon,
        "values": values,
        "created_by_id": record.created_by_id,
        "last_edited_by_id": record.last_edited_by_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def serialize_record_page(records: list[Record]) -> list[dict[str, Any]]:
    """페이지 안의 속성 값과 관계 카드를 각각 한 번에 읽습니다."""
    if not records:
        return []
    stored_rows = list(
        PropertyValue.objects.filter(record_id__in=[record.id for record in records])
        .select_related("property")
        .order_by("property__position", "property_id")
    )
    grouped: dict[int, list[PropertyValue]] = {}
    relation_ids: list[int] = []
    for item in stored_rows:
        grouped.setdefault(item.record_id, []).append(item)
        if item.property.type == Property.Type.RELATION:
            relation_ids.extend(_relation_ids(item.json_value))
    cards = {card["id"]: card for card in _relation_cards(relation_ids)}
    payloads: list[dict[str, Any]] = []
    for record in records:
        values: dict[str, Any] = {}
        for item in grouped.get(record.id, []):
            value = export_value(item)
            if item.property.type == Property.Type.RELATION:
                value = [cards[record_id] for record_id in _relation_ids(value) if record_id in cards]
            values[item.property.slug] = value
        payloads.append(_record_summary(record, values))
    return payloads


def serialize_record(record: Record, *, include_blocks: bool = False) -> dict[str, Any]:
    payload = _record_summary(record, export_values(record))
    if include_blocks:
        blocks = record.blocks.order_by("position", "id")
        payload["blocks"] = [serialize_block(block) for block in blocks]
        record.refresh_from_db(fields=["collab_seq"])
        payload["collab_seq"] = record.collab_seq
    return payload


def title_property(database: Database) -> Property:
    prop = database.properties.filter(type=Property.Type.TITLE).first()
    if prop is None:
        raise HttpError(400, "제목 속성이 없습니다.")
    return prop


def _options(prop: Property) -> list[dict[str, Any]]:
    options = (prop.config or {}).get("options") or []
    if not isinstance(options, list):
        raise HttpError(400, "선택 옵션 형식이 올바르지 않습니다.")
    return options


def canonical_option_name(prop: Property, raw: Any) -> str:
    token = str(raw).strip()
    for option in _options(prop):
        if token in {str(option.get("id", "")), str(option.get("name", ""))}:
            return str(option["name"])
    raise HttpError(400, f"{prop.name}에 없는 값입니다.")


def normalize_property_config(prop_type: str, config: dict | None, workspace_id: int) -> dict:
    payload = dict(config or {})
    if prop_type not in Property.Type.values:
        raise HttpError(400, "지원하지 않는 속성 타입입니다.")
    if prop_type in OPTION_TYPES:
        options = payload.get("options")
        if not isinstance(options, list) or not options:
            raise HttpError(400, "선택 옵션이 필요합니다.")
        cleaned = []
        seen: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                raise HttpError(400, "선택 옵션 형식이 올바르지 않습니다.")
            option_id = validate_slug(str(option.get("id", "")))
            name = str(option.get("name", "")).strip()
            if not name:
                raise HttpError(400, "선택 옵션 이름이 필요합니다.")
            if option_id in seen or name in seen:
                raise HttpError(400, "선택 옵션이 중복되었습니다.")
            seen.add(option_id)
            seen.add(name)
            cleaned.append(
                {
                    "id": option_id,
                    "name": name,
                    "color": str(option.get("color") or "gray"),
                }
            )
        payload["options"] = cleaned
        return payload
    if prop_type == Property.Type.RELATION:
        database_id = payload.get("database_id")
        if not isinstance(database_id, int):
            raise HttpError(400, "관계 대상 데이터베이스가 필요합니다.")
        target = Database.objects.filter(id=database_id, workspace_id=workspace_id).first()
        if target is None:
            raise HttpError(400, "관계 대상 데이터베이스를 찾을 수 없습니다.")
        cleaned = {"database_id": target.id}
        synced = payload.get("synced_property_id")
        if synced is not None:
            if isinstance(synced, bool) or not isinstance(synced, int):
                raise HttpError(400, "반대 관계 속성은 id여야 합니다.")
            cleaned["synced_property_id"] = synced
            cleaned["two_way"] = True
        elif payload.get("two_way") is True:
            cleaned["two_way"] = True
        return cleaned
    return payload


_LOOSE_DATE = re.compile(
    r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?"
    r"(?:\s*(?:T|\s)\s*(오전|오후)?\s*(\d{1,2})\s*[:시]\s*(\d{2})?)?"
)
_RANGE_SPLIT = re.compile(r"\s*(?:~|∼|→|–|—|\s-\s|부터)\s*")


def _loose_datetime(text: str) -> datetime | None:
    """`2026.11.10`, `2026년 11월 10일 오후 3:00 (GMT+9)` 같은 흔한 표기를 읽습니다."""
    cleaned = re.sub(r"\((?:GMT|UTC)[^)]*\)|\bKST\b", "", text).strip()
    match = _LOOSE_DATE.search(cleaned)
    if match is None:
        return None
    year, month, day, ampm, hour, minute = match.groups()
    clock = 0
    if hour is not None:
        clock = int(hour)
        if ampm == "오후" and clock < 12:
            clock += 12
        elif ampm == "오전" and clock == 12:
            clock = 0
    try:
        return datetime(int(year), int(month), int(day), clock, int(minute or 0))
    except ValueError:
        return None


def _parse_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        parsed: datetime | None = raw
    else:
        text = str(raw).strip()
        parsed = None
        try:
            parsed = parse_datetime(text)
            if parsed is None:
                parsed_date = parse_date(text)
                if parsed_date is not None:
                    parsed = datetime.combine(parsed_date, time.min)
        except ValueError:
            parsed = None
        if parsed is None:
            parsed = _loose_datetime(text)
        if parsed is None:
            raise HttpError(400, f"날짜 형식이 올바르지 않습니다: {text[:40]}")
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _split_date_range(raw: Any) -> Any:
    """`2026-11-09 ~ 2026-11-15` 한 문자열을 `{start, end}`로 바꿉니다."""
    if not isinstance(raw, str):
        return raw
    parts = [part for part in _RANGE_SPLIT.split(raw.strip()) if part]
    if len(parts) == 2 and all(_loose_datetime(part) or _is_iso(part) for part in parts):
        return {"start": parts[0], "end": parts[1]}
    return raw


def _is_iso(text: str) -> bool:
    try:
        return parse_datetime(text) is not None or parse_date(text) is not None
    except ValueError:
        return False


def _clear_value(record: Record, prop: Property) -> None:
    stored = PropertyValue.objects.filter(record=record, property=prop).first()
    if stored is not None:
        stored.delete()
    if prop.type == Property.Type.RELATION:
        old_ids = list(
            RelationLink.objects.filter(property=prop, from_record=record).values_list(
                "to_record_id", flat=True
            )
        )
        for link in RelationLink.objects.filter(property=prop, from_record=record):
            link.delete()
        _sync_reverse_links(prop, record, old_ids, [])


def _store_columns(record: Record, prop: Property, columns: dict[str, Any]) -> None:
    stored = PropertyValue.objects.filter(record=record, property=prop).first()
    if stored is None:
        stored = PropertyValue(record=record, property=prop)
    stored.text_value = columns.get("text_value") or ""
    stored.number_value = columns.get("number_value")
    stored.date_start = columns.get("date_start")
    stored.date_end = columns.get("date_end")
    stored.checkbox_value = columns.get("checkbox_value")
    stored.json_value = columns.get("json_value")
    stored.save()


def _replace_links(prop: Property, record: Record, target_ids: list[int]) -> None:
    old_ids = list(
        RelationLink.objects.filter(property=prop, from_record=record).values_list(
            "to_record_id", flat=True
        )
    )
    for link in RelationLink.objects.filter(property=prop, from_record=record):
        link.delete()
    for target_id in target_ids:
        RelationLink.objects.create(
            property=prop,
            from_record=record,
            to_record_id=target_id,
        )
    _sync_reverse_links(prop, record, old_ids, target_ids)


def _reverse_property(prop: Property) -> Property | None:
    synced_id = (prop.config or {}).get("synced_property_id")
    if not isinstance(synced_id, int) or synced_id == prop.id:
        return None
    reverse = Property.objects.filter(id=synced_id, type=Property.Type.RELATION).first()
    if reverse is None:
        return None
    if (reverse.config or {}).get("synced_property_id") != prop.id:
        return None
    return reverse


def _write_relation_ids(prop: Property, record_id: int) -> None:
    ids = list(
        RelationLink.objects.filter(property=prop, from_record_id=record_id).values_list(
            "to_record_id", flat=True
        )
    )
    record = Record.objects.filter(id=record_id).first()
    if record is None:
        return
    if not ids:
        stored = PropertyValue.objects.filter(record_id=record_id, property=prop).first()
        if stored is not None:
            stored.delete()
        return
    _store_columns(
        record,
        prop,
        {"json_value": ids, "text_value": ",".join(str(item) for item in ids)},
    )


def _sync_reverse_links(
    prop: Property,
    record: Record,
    old_ids: list[int],
    new_ids: list[int],
) -> None:
    reverse = _reverse_property(prop)
    if reverse is None:
        return
    old_set = set(old_ids)
    new_set = set(new_ids)
    for target_id in old_set - new_set:
        for link in RelationLink.objects.filter(
            property=reverse,
            from_record_id=target_id,
            to_record=record,
        ):
            link.delete()
        _write_relation_ids(reverse, target_id)
    for target_id in new_set - old_set:
        if not RelationLink.objects.filter(
            property=reverse,
            from_record_id=target_id,
            to_record=record,
        ).exists():
            RelationLink.objects.create(
                property=reverse,
                from_record_id=target_id,
                to_record=record,
            )
        _write_relation_ids(reverse, target_id)


def _unique_property_slug(database: Database, base: str) -> str:
    slug = base[:50]
    number = 2
    while database.properties.filter(slug=slug).exists():
        suffix = f"_{number}"
        slug = f"{base[: 50 - len(suffix)]}{suffix}"
        number += 1
    return slug


def _bind_two_way(prop: Property) -> Property | None:
    if prop.type != Property.Type.RELATION or not (prop.config or {}).get("two_way"):
        return None
    synced_id = (prop.config or {}).get("synced_property_id")
    if synced_id is not None:
        _link_existing_reverse(prop, int(synced_id))
        return None
    target = Database.objects.filter(id=prop.config["database_id"]).first()
    if target is None:
        raise HttpError(400, "관계 대상 데이터베이스를 찾을 수 없습니다.")
    reverse = Property.objects.create(
        database=target,
        name=prop.name,
        slug=_unique_property_slug(target, f"{prop.slug}_rel"),
        type=Property.Type.RELATION,
        config={
            "database_id": prop.database_id,
            "two_way": True,
            "synced_property_id": prop.id,
        },
        position=(target.properties.order_by("-position").values_list("position", flat=True).first() or 0)
        + 1,
    )
    prop.config = {**(prop.config or {}), "two_way": True, "synced_property_id": reverse.id}
    prop.save(update_fields=["config", "updated_at"])
    return reverse


def _link_existing_reverse(prop: Property, synced_id: int) -> None:
    if synced_id == prop.id:
        raise HttpError(400, "관계 속성은 자기 자신과 묶을 수 없습니다.")
    other = Property.objects.filter(id=synced_id, type=Property.Type.RELATION).first()
    if other is None or other.database_id != (prop.config or {}).get("database_id"):
        raise HttpError(400, "반대 관계 속성을 찾을 수 없습니다.")
    if (other.config or {}).get("database_id") != prop.database_id:
        raise HttpError(400, "반대 관계의 대상이 이 데이터베이스가 아닙니다.")
    other_synced = (other.config or {}).get("synced_property_id")
    if other_synced not in (None, prop.id):
        raise HttpError(400, "이미 다른 속성과 묶인 관계입니다.")
    current = (prop.config or {}).get("synced_property_id")
    if current not in (None, other.id):
        raise HttpError(400, "이미 다른 속성과 묶인 관계입니다.")
    other.config = {
        **(other.config or {}),
        "database_id": prop.database_id,
        "two_way": True,
        "synced_property_id": prop.id,
    }
    other.save(update_fields=["config", "updated_at"])
    prop.config = {**(prop.config or {}), "two_way": True, "synced_property_id": other.id}
    prop.save(update_fields=["config", "updated_at"])


def _coerce(prop: Property, raw: Any, record: Record) -> dict[str, Any]:
    prop_type = prop.type
    if prop_type in TEXT_TYPES or prop_type in {Property.Type.SELECT, Property.Type.STATUS}:
        if prop_type in {Property.Type.SELECT, Property.Type.STATUS}:
            text = canonical_option_name(prop, raw)
            return {"text_value": text, "json_value": {"name": text}}
        text = str(raw).strip()
        if prop_type == Property.Type.EMAIL and not EMAIL_PATTERN.match(text):
            raise HttpError(400, "이메일 형식이 올바르지 않습니다.")
        if prop_type == Property.Type.URL and not (
            text.startswith("http://") or text.startswith("https://")
        ):
            raise HttpError(400, "URL은 http:// 또는 https://로 시작해야 합니다.")
        if prop_type == Property.Type.PHONE:
            digits = re.sub(r"\D", "", text)
            if len(digits) < 8:
                raise HttpError(400, "전화번호 형식이 올바르지 않습니다.")
        if prop_type == Property.Type.TITLE and not text:
            raise HttpError(400, "제목은 비울 수 없습니다.")
        return {"text_value": text}
    if prop_type == Property.Type.NUMBER:
        try:
            number = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise HttpError(400, "숫자 형식이 올바르지 않습니다.") from None
        return {"number_value": number, "text_value": format(number, "f")}
    if prop_type == Property.Type.DATE:
        raw = _split_date_range(raw)
        try:
            if isinstance(raw, dict):
                if not raw.get("start"):
                    raise HttpError(400, "날짜 시작 값이 필요합니다.")
                start = _parse_datetime(raw.get("start"))
                end = _parse_datetime(raw.get("end")) if raw.get("end") else None
                if end is not None and end < start:
                    raise HttpError(400, "날짜 종료는 시작보다 빠를 수 없습니다.")
            else:
                start = _parse_datetime(raw)
                end = None
        except HttpError as exc:
            if "날짜 형식" in exc.message:
                raise HttpError(400, f"'{prop.name}' 속성: {exc.message}") from None
            raise
        return {"date_start": start, "date_end": end, "text_value": start.isoformat()}
    if prop_type == Property.Type.CHECKBOX:
        if not isinstance(raw, bool):
            raise HttpError(400, "체크박스 값은 true 또는 false여야 합니다.")
        return {"checkbox_value": raw, "text_value": "true" if raw else "false"}
    if prop_type == Property.Type.MULTI_SELECT:
        if not isinstance(raw, list) or not raw:
            raise HttpError(400, "다중 선택 값은 목록이어야 합니다.")
        names = [canonical_option_name(prop, item) for item in raw]
        return {"json_value": names, "text_value": "\n".join(names)}
    if prop_type == Property.Type.PEOPLE:
        raw_ids = raw if isinstance(raw, list) else [raw]
        if not raw_ids:
            raise HttpError(400, "사람 값이 필요합니다.")
        user_ids: list[int] = []
        for item in raw_ids:
            if isinstance(item, bool) or not isinstance(item, int):
                raise HttpError(400, "사람 값은 사용자 id여야 합니다.")
            if item not in user_ids:
                user_ids.append(item)
        member_ids = set(
            WorkspaceMember.objects.filter(
                workspace_id=record.database.workspace_id,
                user_id__in=user_ids,
            ).values_list("user_id", flat=True)
        )
        if set(user_ids) - member_ids:
            raise HttpError(400, "같은 워크스페이스 멤버만 담당자로 지정할 수 있습니다.")
        return {"json_value": user_ids, "text_value": ",".join(str(item) for item in user_ids)}
    if prop_type == Property.Type.FILES:
        if not isinstance(raw, list):
            raise HttpError(400, "파일 값은 목록이어야 합니다.")
        files = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("url"):
                raise HttpError(400, "파일에는 url이 필요합니다.")
            files.append({"name": str(item.get("name") or ""), "url": str(item["url"])})
        return {"json_value": files, "text_value": "\n".join(item["url"] for item in files)}
    if prop_type == Property.Type.RELATION:
        raw_ids = raw if isinstance(raw, list) else [raw]
        target_database_id = (prop.config or {}).get("database_id")
        if not isinstance(target_database_id, int):
            raise HttpError(400, "관계 대상 데이터베이스가 없습니다.")
        relation_ids: list[int] = []
        for item in raw_ids:
            if isinstance(item, bool) or not isinstance(item, int):
                raise HttpError(400, "관계 값은 레코드 id여야 합니다.")
            if item not in relation_ids:
                relation_ids.append(item)
        found = set(
            Record.objects.filter(
                id__in=relation_ids,
                database_id=target_database_id,
                database__workspace_id=record.database.workspace_id,
            ).values_list("id", flat=True)
        )
        if set(relation_ids) - found:
            raise HttpError(400, "관계로 연결할 수 없는 레코드입니다.")
        return {
            "json_value": relation_ids,
            "text_value": ",".join(str(item) for item in relation_ids),
            "relation_ids": relation_ids,
        }
    raise HttpError(400, "지원하지 않는 속성 타입입니다.")


def fold_date_range_aliases(database: Database, values: dict[str, Any]) -> dict[str, Any]:
    """출장 `period`에 잘못 붙은 start_date, end_date를 기간 값으로 합칩니다."""
    props = {prop.slug: prop for prop in database.properties.all()}
    period = props.get("period")
    if period is None or period.type != Property.Type.DATE:
        return values
    if "start_date" in props or "end_date" in props:
        return values
    if "start_date" not in values and "end_date" not in values:
        return values
    folded = dict(values)
    start_alias = _present_date(folded.pop("start_date", None))
    end_alias = _present_date(folded.pop("end_date", None))
    current = folded.get("period")
    if isinstance(current, dict):
        start = _present_date(current.get("start")) or start_alias or end_alias
        end = _present_date(current.get("end")) or end_alias or start
    elif _present_date(current):
        start = current
        end = end_alias or start_alias or current
    else:
        start = start_alias or end_alias
        end = end_alias or start
    if start:
        payload: dict[str, Any] = {"start": start}
        if end:
            payload["end"] = end
        folded["period"] = payload
    return folded


def _present_date(raw: Any) -> Any:
    if raw is None or raw == "" or raw == []:
        return None
    return raw


def apply_values(record: Record, values: dict[str, Any]) -> None:
    values = fold_date_range_aliases(record.database, values)
    props = {prop.slug: prop for prop in record.database.properties.all()}
    for slug, raw in values.items():
        prop = props.get(slug)
        if prop is None:
            raise HttpError(400, f"속성 {slug}을 찾을 수 없습니다.")
        if raw is None or raw == "" or raw == []:
            if prop.type == Property.Type.TITLE:
                raise HttpError(400, "제목은 비울 수 없습니다.")
            _clear_value(record, prop)
            continue
        columns = _coerce(prop, raw, record)
        relation_ids = columns.pop("relation_ids", None)
        _store_columns(record, prop, columns)
        if prop.type == Property.Type.TITLE:
            record.title = columns["text_value"]
        if relation_ids is not None:
            _replace_links(prop, record, relation_ids)


def _validate_block_type(block_type: str) -> str:
    if block_type not in Block.Type.values:
        raise HttpError(400, "지원하지 않는 블록 타입입니다.")
    return block_type


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _validate_string_map(content: dict, key: str, *, label: str) -> None:
    raw = content.get(key)
    if raw is None:
        return
    if not isinstance(raw, dict) or any(not isinstance(name, str) or not isinstance(item, str) for name, item in raw.items()):
        raise HttpError(400, f"{label}은 문자열 맵이어야 합니다.")


def _validate_align_map(content: dict, key: str) -> None:
    raw = content.get(key)
    if raw is None:
        return
    if not isinstance(raw, dict) or any(
        not isinstance(name, str) or item not in TABLE_ALIGNS for name, item in raw.items()
    ):
        raise HttpError(400, "정렬은 Left, Center, Right여야 합니다.")


def _validate_width_map(content: dict, key: str) -> None:
    raw = content.get(key)
    if raw is None:
        return
    if not isinstance(raw, dict) or any(
        not isinstance(name, str) or not _positive_number(item) for name, item in raw.items()
    ):
        raise HttpError(400, "열 너비는 0보다 큰 숫자여야 합니다.")


def assert_block_shape(block_type: str, parent_type: str | None) -> None:
    required = {
        Block.Type.SIMPLE_TABLE_ROW: (
            {Block.Type.SIMPLE_TABLE},
            "표 행은 표 블록 아래에만 둘 수 있습니다.",
        ),
        Block.Type.SIMPLE_TABLE_CELL: (
            {Block.Type.SIMPLE_TABLE_ROW},
            "표 칸은 표 행 아래에만 둘 수 있습니다.",
        ),
        Block.Type.SIMPLE_COLUMN: (
            {Block.Type.SIMPLE_COLUMNS},
            "단은 다단 블록 아래에만 둘 수 있습니다.",
        ),
    }
    if block_type in required:
        allowed, message = required[block_type]
        if parent_type not in allowed:
            raise HttpError(400, message)
    limited = {
        Block.Type.SIMPLE_TABLE: (
            {Block.Type.SIMPLE_TABLE_ROW},
            "표 아래에는 표 행만 둘 수 있습니다.",
        ),
        Block.Type.SIMPLE_TABLE_ROW: (
            {Block.Type.SIMPLE_TABLE_CELL},
            "표 행 아래에는 표 칸만 둘 수 있습니다.",
        ),
        Block.Type.SIMPLE_COLUMNS: (
            {Block.Type.SIMPLE_COLUMN},
            "다단 아래에는 단만 둘 수 있습니다.",
        ),
    }
    if parent_type in limited:
        allowed, message = limited[parent_type]
        if block_type not in allowed:
            raise HttpError(400, message)


def _validate_rich_text(items: Any, workspace_id: int) -> None:
    if not isinstance(items, list) or not items:
        raise HttpError(400, "rich_text는 한 항목 이상이어야 합니다.")
    user_ids: list[int] = []
    record_ids: list[int] = []
    page_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise HttpError(400, "rich_text 항목에는 문자열 text가 필요합니다.")
        has_text = "text" in item
        has_formula = "formula" in item
        if has_formula and not isinstance(item.get("formula"), str):
            raise HttpError(400, "인라인 수식은 문자열이어야 합니다.")
        if has_text and not isinstance(item.get("text"), str):
            raise HttpError(400, "rich_text 항목에는 문자열 text가 필요합니다.")
        if not has_text and not has_formula:
            raise HttpError(400, "rich_text 항목에는 문자열 text가 필요합니다.")
        annotations = item.get("annotations")
        if annotations is not None:
            if not isinstance(annotations, dict):
                raise HttpError(400, "annotations는 객체여야 합니다.")
            if set(annotations) - RICH_TEXT_ANNOTATIONS:
                raise HttpError(400, "지원하지 않는 서식입니다.")
            for key in BOOL_ANNOTATIONS:
                if key in annotations and not isinstance(annotations[key], bool):
                    raise HttpError(400, "서식 값은 true 또는 false여야 합니다.")
            if "color" in annotations and not isinstance(annotations["color"], str):
                raise HttpError(400, "색은 문자열이어야 합니다.")
        href = item.get("href")
        if href is not None and (
            not isinstance(href, str) or not href.startswith(("http://", "https://"))
        ):
            raise HttpError(400, "링크는 http:// 또는 https://로 시작해야 합니다.")
        mention = item.get("mention")
        if mention is None:
            continue
        if not isinstance(mention, dict):
            raise HttpError(400, "멘션 형식이 올바르지 않습니다.")
        mention_type = mention.get("type")
        if mention_type == "user":
            user_id = mention.get("user_id")
            if isinstance(user_id, bool) or not isinstance(user_id, int):
                raise HttpError(400, "멘션 사용자는 id여야 합니다.")
            user_ids.append(user_id)
        elif mention_type == "record":
            record_id = mention.get("record_id")
            if isinstance(record_id, bool) or not isinstance(record_id, int):
                raise HttpError(400, "멘션 레코드는 id여야 합니다.")
            record_ids.append(record_id)
        elif mention_type == "page":
            page_id = mention.get("page_id")
            if isinstance(page_id, bool) or not isinstance(page_id, int):
                raise HttpError(400, "멘션 페이지는 id여야 합니다.")
            page_ids.append(page_id)
        else:
            raise HttpError(400, "멘션 타입은 user, record, page입니다.")
    if user_ids:
        found = set(
            WorkspaceMember.objects.filter(
                workspace_id=workspace_id, user_id__in=user_ids
            ).values_list("user_id", flat=True)
        )
        if any(user_id not in found for user_id in user_ids):
            raise HttpError(400, "같은 워크스페이스 멤버만 멘션할 수 있습니다.")
    if record_ids:
        found = set(
            Record.objects.filter(
                id__in=record_ids, database__workspace_id=workspace_id
            ).values_list("id", flat=True)
        )
        if any(record_id not in found for record_id in record_ids):
            raise HttpError(400, "멘션할 수 없는 레코드입니다.")
    if page_ids:
        found = set(
            Page.objects.filter(id__in=page_ids, workspace_id=workspace_id).values_list(
                "id", flat=True
            )
        )
        if any(page_id not in found for page_id in page_ids):
            raise HttpError(400, "멘션할 수 없는 페이지입니다.")


def _require_text_or_rich_text(content: dict, workspace_id: int) -> None:
    if "rich_text" in content:
        _validate_rich_text(content.get("rich_text"), workspace_id)
        return
    if "text" in content and not isinstance(content.get("text"), str):
        raise HttpError(400, "블록 본문은 문자열이어야 합니다.")


def validate_block_content(block_type: str, content: Any, workspace_id: int) -> dict:
    if not isinstance(content, dict):
        raise HttpError(400, "블록 내용은 객체여야 합니다.")
    if block_type == Block.Type.DIVIDER:
        return content
    if block_type == Block.Type.SIMPLE_TABLE:
        for key in ("enable_header_row", "enable_header_column"):
            if key in content and not isinstance(content.get(key), bool):
                raise HttpError(400, "표 머리글 설정은 true 또는 false여야 합니다.")
        _validate_width_map(content, "column_widths")
        _validate_string_map(content, "row_colors", label="행 색")
        _validate_string_map(content, "column_colors", label="열 색")
        _validate_align_map(content, "column_aligns")
        _validate_align_map(content, "row_aligns")
        return content
    if block_type in {Block.Type.SIMPLE_TABLE_ROW, Block.Type.SIMPLE_TABLE_CELL, Block.Type.SIMPLE_COLUMNS}:
        return content
    if block_type == Block.Type.SIMPLE_COLUMN:
        if "ratio" in content and not _positive_number(content.get("ratio")):
            raise HttpError(400, "단 비율은 0보다 큰 숫자여야 합니다.")
        return content
    if block_type == Block.Type.MATH_EQUATION:
        if "formula" in content and not isinstance(content.get("formula"), str):
            raise HttpError(400, "수식은 문자열이어야 합니다.")
        return content
    if block_type == Block.Type.LINK_PREVIEW:
        url = content.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise HttpError(400, "북마크 URL은 http:// 또는 https://로 시작해야 합니다.")
        for key in ("title", "description", "image"):
            if key in content and content.get(key) is not None and not isinstance(content.get(key), str):
                raise HttpError(400, "북마크 미리보기는 문자열이어야 합니다.")
        return content
    if block_type == Block.Type.IMAGE:
        object_key = content.get("object_key")
        if object_key is not None:
            if not isinstance(object_key, str):
                raise HttpError(400, "이미지 저장 경로는 문자열이어야 합니다.")
            from document.storage import assert_block_object_key

            assert_block_object_key(workspace_id, object_key)
        else:
            url = content.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise HttpError(400, "이미지는 url 또는 object_key가 필요합니다.")
        file_name = content.get("file_name")
        if file_name is not None and not isinstance(file_name, str):
            raise HttpError(400, "파일 이름은 문자열이어야 합니다.")
        if "rich_text" in content or "text" in content:
            _require_text_or_rich_text(content, workspace_id)
        return content
    if block_type == Block.Type.CODE:
        if not isinstance(content.get("text"), str):
            raise HttpError(400, "코드 블록에는 text가 필요합니다.")
        if "language" in content and not isinstance(content.get("language"), str):
            raise HttpError(400, "코드 언어는 문자열이어야 합니다.")
        return content
    if block_type == Block.Type.TO_DO and "checked" in content and not isinstance(
        content.get("checked"), bool
    ):
        raise HttpError(400, "할 일 체크는 true 또는 false여야 합니다.")
    if block_type == Block.Type.CALLOUT and "icon" in content and not isinstance(
        content.get("icon"), str
    ):
        raise HttpError(400, "콜아웃 아이콘은 문자열이어야 합니다.")
    _require_text_or_rich_text(content, workspace_id)
    return content


def create_block_tree(
    record: Record | None,
    blocks: list[dict],
    parent: Block | None,
    page: Page | None = None,
) -> None:
    if record is None and page is None:
        raise HttpError(400, "블록을 저장할 페이지가 없습니다.")
    workspace_id = record.database.workspace_id if record is not None else page.workspace_id
    for index, data in enumerate(blocks or []):
        block_type = _validate_block_type(str(data.get("type") or ""))
        assert_block_shape(block_type, None if parent is None else parent.type)
        content = validate_block_content(block_type, data.get("content") or {}, workspace_id)
        created = Block.objects.create(
            record=record,
            page=None if record is not None else page,
            parent=parent,
            type=block_type,
            content=content,
            position=int(data.get("position", index)),
        )
        create_block_tree(record, data.get("children") or [], created, page)


def _subtree_ids(root: Block) -> list[int]:
    if root.record_id:
        rows = Block.objects.filter(record_id=root.record_id).values_list("id", "parent_id")
    else:
        rows = Block.objects.filter(page_id=root.page_id).values_list("id", "parent_id")
    children: dict[int | None, list[int]] = {}
    for block_id, parent_id in rows:
        children.setdefault(parent_id, []).append(block_id)
    collected: list[int] = []

    def walk(block_id: int) -> None:
        for child_id in children.get(block_id, []):
            walk(child_id)
        collected.append(block_id)

    walk(root.id)
    return collected


def soft_delete_blocks(block_ids: list[int]) -> None:
    if block_ids:
        Block.objects.filter(id__in=block_ids).update(deleted_at=timezone.now())


def replace_blocks(record: Record, blocks: list[dict], actor_id: int | None = None) -> None:
    soft_delete_blocks(list(record.blocks.values_list("id", flat=True)))
    create_block_tree(record, blocks, None)
    publish_collab_event("record", record.id, "reload", actor_id, None, None)


def _snapshot(record: Record) -> dict[str, Any]:
    record.refresh_from_db(fields=["title", "updated_at"])
    return {
        "title": record.title,
        "values": export_values(record),
        "block_count": record.blocks.count(),
    }


def _block_snapshot(record: Record) -> dict[str, Any]:
    """블록만 고치는 동작용입니다. 제목과 속성 값은 읽지 않습니다."""
    return {"block_count": record.blocks.count()}


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if before.get("title") != after.get("title"):
        changes["title"] = {"before": before.get("title"), "after": after.get("title")}
    if before.get("values") != after.get("values"):
        changes["values"] = {"before": before.get("values"), "after": after.get("values")}
    if before.get("block_count") != after.get("block_count"):
        changes["blocks"] = {
            "before": before.get("block_count"),
            "after": after.get("block_count"),
        }
    return changes


def log_activity(
    record: Record,
    user,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    source: str,
) -> None:
    if action == RecordActivity.Action.CREATED:
        changes: dict[str, Any] = {"after": after}
    else:
        changes = _diff(before, after)
        if not changes:
            return
    RecordActivity.objects.create(
        record=record,
        actor=user,
        action=action,
        changes=changes,
        source=source,
    )


def _save_integrity(func):
    try:
        return func()
    except IntegrityError:
        raise HttpError(400, "이미 같은 키가 있습니다.") from None


@transaction.atomic
def create_workspace(user, name: str, slug: str) -> dict[str, Any]:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise HttpError(400, "워크스페이스 이름이 필요합니다.")

    def _create():
        workspace = Workspace.objects.create(name=cleaned_name, slug=validate_slug(slug))
        WorkspaceMember.objects.create(
            workspace=workspace,
            user=user,
            role=WorkspaceMember.Role.OWNER,
        )
        return serialize_workspace(workspace, WorkspaceMember.Role.OWNER)

    return _save_integrity(_create)


@transaction.atomic
def update_workspace(user, workspace_id: int, data: dict[str, Any]) -> dict[str, Any]:
    membership = get_membership(user, workspace_id)
    if membership.role not in {WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN}:
        raise HttpError(403, "워크스페이스를 수정할 권한이 없습니다.")
    workspace = membership.workspace
    if "name" in data and data["name"] is not None:
        cleaned = str(data["name"]).strip()
        if not cleaned:
            raise HttpError(400, "워크스페이스 이름이 필요합니다.")
        workspace.name = cleaned
    if "slug" in data and data["slug"] is not None:
        workspace.slug = validate_slug(str(data["slug"]))

    def _save():
        workspace.save()
        return serialize_workspace(workspace, membership.role)

    return _save_integrity(_save)


@transaction.atomic
def delete_workspace(user, workspace_id: int) -> None:
    membership = get_membership(user, workspace_id)
    if membership.role != WorkspaceMember.Role.OWNER:
        raise HttpError(403, "워크스페이스를 삭제할 권한이 없습니다.")
    for database in list(Database.objects.filter(workspace_id=workspace_id)):
        delete_database(user, database.id)
    for page in Page.objects.filter(workspace_id=workspace_id):
        page.delete()
    for member in WorkspaceMember.objects.filter(workspace_id=workspace_id):
        member.delete()
    membership.workspace.delete()


@transaction.atomic
def create_database(user, data: dict[str, Any]) -> dict[str, Any]:
    get_membership(user, data["workspace_id"])

    def _create():
        database = Database.objects.create(
            workspace_id=data["workspace_id"],
            name=str(data["name"]).strip(),
            slug=validate_slug(str(data["slug"])),
            description=data.get("description") or "",
            icon=data.get("icon") or "",
            section=str(data.get("section") or "").strip(),
            section_slug=_section_slug(data.get("section_slug")),
            position=data.get("position") or 0,
        )
        if not database.name:
            raise HttpError(400, "데이터베이스 이름이 필요합니다.")
        Property.objects.create(
            database=database,
            name="제목",
            slug="title",
            type=Property.Type.TITLE,
            position=0,
        )
        from workspace.tree import ensure_database_page

        page = ensure_database_page(database)
        publish_workspace_event(database.workspace_id, "database", "created", database.id, user.id)
        publish_workspace_event(database.workspace_id, "page", "created", page.id, user.id)
        return serialize_database(database, detail=True)

    return _save_integrity(_create)


@transaction.atomic
def update_database(user, database_id: int, data: dict[str, Any]) -> dict[str, Any]:
    database = get_database(user, database_id)
    if data.get("name") is not None:
        database.name = str(data["name"]).strip()
        if not database.name:
            raise HttpError(400, "데이터베이스 이름이 필요합니다.")
    if data.get("slug") is not None:
        database.slug = validate_slug(str(data["slug"]))
    if data.get("description") is not None:
        database.description = data["description"]
    if data.get("icon") is not None:
        database.icon = data["icon"]
    if data.get("section") is not None:
        database.section = str(data["section"]).strip()
    if data.get("section_slug") is not None:
        database.section_slug = _section_slug(data.get("section_slug"))
    if data.get("position") is not None:
        database.position = data["position"]
    if "access" in data:
        from workspace.access import clean_access, require_access_manager

        require_access_manager(user, database.workspace_id)
        database.access = clean_access(data.get("access"))

    def _save():
        database.save()
        from workspace.tree import ensure_database_page

        page = ensure_database_page(database)
        publish_workspace_event(database.workspace_id, "database", "updated", database.id, user.id)
        publish_workspace_event(database.workspace_id, "page", "updated", page.id, user.id)
        return serialize_database(database, detail=True)

    return _save_integrity(_save)


def delete_database_object(database: Database) -> None:
    for record in Record.objects.filter(database=database):
        delete_record_object(record)
    for prop in Property.objects.filter(database=database):
        prop.delete()
    for view in View.objects.filter(database=database):
        view.delete()
    for template in DatabaseTemplate.objects.filter(database=database):
        template.delete()
    database.delete()


@transaction.atomic
def delete_database(user, database_id: int) -> None:
    database = get_database(user, database_id)
    page = Page.objects.filter(database=database, kind=Page.Kind.DATABASE).first()
    if page is not None:
        from workspace.tree import delete_database_page

        delete_database_page(user, page)
        return
    workspace_id = database.workspace_id
    deleted_id = database.id
    delete_database_object(database)
    publish_workspace_event(workspace_id, "database", "deleted", deleted_id, user.id)


def _ensure_single_title(database: Database, prop_type: str, current_id: int | None) -> None:
    if prop_type != Property.Type.TITLE:
        return
    existing = database.properties.filter(type=Property.Type.TITLE)
    if current_id is not None:
        existing = existing.exclude(id=current_id)
    if existing.exists():
        raise HttpError(400, "제목 속성은 하나만 둘 수 있습니다.")


@transaction.atomic
def create_property(user, database_id: int, data: dict[str, Any]) -> dict[str, Any]:
    database = get_database(user, database_id)
    prop_type = data["type"]
    _ensure_single_title(database, prop_type, None)
    config = normalize_property_config(prop_type, data.get("config"), database.workspace_id)

    def _create():
        prop = Property.objects.create(
            database=database,
            name=str(data["name"]).strip(),
            slug=validate_slug(str(data["slug"])),
            type=prop_type,
            config=config,
            position=data.get("position") or 0,
        )
        if not prop.name:
            raise HttpError(400, "속성 이름이 필요합니다.")
        reverse = _bind_two_way(prop)
        prop.refresh_from_db()
        publish_workspace_event(database.workspace_id, "property", "created", prop.id, user.id)
        if reverse is not None:
            publish_workspace_event(
                reverse.database.workspace_id, "property", "created", reverse.id, user.id
            )
        return serialize_property(prop)

    return _save_integrity(_create)


@transaction.atomic
def update_property(user, property_id: int, data: dict[str, Any]) -> dict[str, Any]:
    prop = get_property(user, property_id)
    next_type = data.get("type") or prop.type
    type_changed = next_type != prop.type
    if type_changed:
        if prop.type == Property.Type.TITLE or next_type == Property.Type.TITLE:
            raise HttpError(400, "제목 속성의 타입은 바꿀 수 없습니다.")
        if PropertyValue.objects.filter(property=prop).exists():
            raise HttpError(400, "값이 있는 속성의 타입은 바꿀 수 없습니다.")
        prop.type = next_type
    previous_synced = (prop.config or {}).get("synced_property_id")
    if type_changed or ("config" in data and data["config"] is not None):
        prop.config = normalize_property_config(
            prop.type,
            data.get("config") if data.get("config") is not None else prop.config,
            prop.database.workspace_id,
        )
    if data.get("name") is not None:
        prop.name = str(data["name"]).strip()
        if not prop.name:
            raise HttpError(400, "속성 이름이 필요합니다.")
    if data.get("slug") is not None:
        prop.slug = validate_slug(str(data["slug"]))
    if data.get("position") is not None:
        prop.position = data["position"]
    _ensure_single_title(prop.database, prop.type, prop.id)

    def _save():
        prop.save()
        if prop.type == Property.Type.RELATION and (prop.config or {}).get("two_way"):
            _bind_two_way(prop)
            prop.refresh_from_db()
        elif previous_synced:
            _unlink_two_way(prop, int(previous_synced))
        publish_workspace_event(
            prop.database.workspace_id, "property", "updated", prop.id, user.id
        )
        return serialize_property(prop)

    return _save_integrity(_save)


def _unlink_two_way(prop: Property, other_id: int) -> None:
    other = Property.objects.filter(id=other_id).first()
    if other is not None and (other.config or {}).get("synced_property_id") == prop.id:
        config = dict(other.config or {})
        config.pop("synced_property_id", None)
        config.pop("two_way", None)
        other.config = config
        other.save(update_fields=["config", "updated_at"])
    config = dict(prop.config or {})
    config.pop("synced_property_id", None)
    config.pop("two_way", None)
    prop.config = config
    prop.save(update_fields=["config", "updated_at"])


@transaction.atomic
def delete_property(user, property_id: int) -> None:
    prop = get_property(user, property_id)
    if prop.type == Property.Type.TITLE:
        raise HttpError(400, "제목 속성은 지울 수 없습니다.")
    synced_id = (prop.config or {}).get("synced_property_id")
    for stored in PropertyValue.objects.filter(property=prop):
        stored.delete()
    for link in RelationLink.objects.filter(property=prop):
        link.delete()
    workspace_id = prop.database.workspace_id
    property_id = prop.id
    prop.delete()
    if isinstance(synced_id, int):
        other = Property.objects.filter(id=synced_id).first()
        if other is not None and (other.config or {}).get("synced_property_id") == property_id:
            config = dict(other.config or {})
            config.pop("synced_property_id", None)
            config.pop("two_way", None)
            other.config = config
            other.save(update_fields=["config", "updated_at"])
    publish_workspace_event(workspace_id, "property", "deleted", property_id, user.id)


def _normalize_filter_leaf(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or "property" not in item or "op" not in item:
        raise HttpError(400, "필터에는 property와 op가 필요합니다.")
    op = str(item["op"])
    if op not in FILTER_OPS:
        raise HttpError(400, "지원하지 않는 필터 연산입니다.")
    return {"property": str(item["property"]), "op": op, "value": item.get("value")}


def _normalize_filter_node(node: Any, depth: int) -> dict[str, Any]:
    if (
        isinstance(node, dict)
        and "filters" in node
        and "property" not in node
        and node.get("op") in FILTER_GROUP_OPS
    ):
        if depth >= 2:
            raise HttpError(400, "필터 그룹은 두 단계까지만 중첩할 수 있습니다.")
        children = node.get("filters")
        if not isinstance(children, list) or not children:
            raise HttpError(400, "필터 그룹에는 조건이 필요합니다.")
        return {
            "op": str(node["op"]),
            "filters": [_normalize_filter_node(child, depth + 1) for child in children],
        }
    return _normalize_filter_leaf(node)


def _normalize_filters(items: Any) -> list[dict[str, Any]] | dict[str, Any]:
    if items is None:
        return []
    if isinstance(items, list):
        return [_normalize_filter_node(item, 0) for item in items]
    if isinstance(items, dict):
        return _normalize_filter_node(items, 0)
    raise HttpError(400, "필터는 목록이거나 그룹이어야 합니다.")


def _normalize_filter_items(items: Any) -> list[dict[str, Any]]:
    normalized = _normalize_filters(items)
    if isinstance(normalized, dict):
        raise HttpError(400, "필터는 목록이어야 합니다.")
    return normalized


def _property_by_slug(database: Database, slug: Any) -> Property | None:
    if not isinstance(slug, str) or not slug:
        return None
    return database.properties.filter(slug=slug).first()


def validate_view_config(database: Database, view_type: str, config: Any) -> dict:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise HttpError(400, "보기 설정은 객체여야 합니다.")
    if view_type == View.Type.BOARD:
        slug = config.get("group_by")
        if not isinstance(slug, str) or not slug:
            raise HttpError(400, "보드 보기에는 group_by가 필요합니다.")
        prop = _property_by_slug(database, slug)
        if prop is None or prop.type not in GROUP_PROPERTY_TYPES:
            raise HttpError(400, "보드는 선택, 상태, 다중 선택 속성으로만 묶을 수 있습니다.")
    elif view_type == View.Type.CALENDAR:
        slug = config.get("date_property")
        if not isinstance(slug, str) or not slug:
            raise HttpError(400, "캘린더 보기에는 date_property가 필요합니다.")
        prop = _property_by_slug(database, slug)
        if prop is None or prop.type != Property.Type.DATE:
            raise HttpError(400, "캘린더는 날짜 속성만 쓸 수 있습니다.")
    elif view_type == View.Type.GALLERY:
        cover = config.get("cover_property")
        if cover not in (None, ""):
            prop = _property_by_slug(database, cover)
            if prop is None or prop.type not in COVER_PROPERTY_TYPES:
                raise HttpError(400, "갤러리 커버는 파일 또는 URL 속성만 쓸 수 있습니다.")
    elif view_type == View.Type.TABLE:
        slug = config.get("group_by")
        if slug not in (None, ""):
            prop = _property_by_slug(database, slug)
            if prop is None or prop.type not in GROUP_PROPERTY_TYPES:
                raise HttpError(400, "표 그룹은 선택, 상태, 다중 선택 속성만 쓸 수 있습니다.")
    hidden = config.get("hidden_properties", [])
    if hidden is None:
        hidden = []
    if not isinstance(hidden, list) or any(not isinstance(item, str) for item in hidden):
        raise HttpError(400, "숨길 속성은 slug 목록이어야 합니다.")
    for slug in hidden:
        prop = _property_by_slug(database, slug)
        if prop is None:
            raise HttpError(400, "숨길 속성을 찾을 수 없습니다.")
        if prop.type == Property.Type.TITLE:
            raise HttpError(400, "제목 속성은 숨길 수 없습니다.")
    widths = config.get("column_widths", {})
    if widths is None:
        widths = {}
    if not isinstance(widths, dict):
        raise HttpError(400, "열 너비는 객체여야 합니다.")
    for slug, width in widths.items():
        if _property_by_slug(database, slug) is None:
            raise HttpError(400, "열 너비의 속성을 찾을 수 없습니다.")
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise HttpError(400, "열 너비는 1 이상의 정수여야 합니다.")
    return config


def _normalize_sort_items(items: Any) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise HttpError(400, "정렬은 목록이어야 합니다.")
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or "property" not in item:
            raise HttpError(400, "정렬에는 property가 필요합니다.")
        direction = str(item.get("direction") or "asc")
        if direction not in {"asc", "desc"}:
            raise HttpError(400, "정렬 방향은 asc 또는 desc입니다.")
        cleaned.append({"property": str(item["property"]), "direction": direction})
    return cleaned


@transaction.atomic
def create_view(user, database_id: int, data: dict[str, Any]) -> dict[str, Any]:
    database = get_database(user, database_id)
    view_type = data.get("type") or View.Type.TABLE
    if view_type not in View.Type.values:
        raise HttpError(400, "지원하지 않는 보기 타입입니다.")
    view = View.objects.create(
        database=database,
        name=str(data["name"]).strip(),
        type=view_type,
        filters=_normalize_filters(data.get("filters")),
        sorts=_normalize_sort_items(data.get("sorts")),
        config=validate_view_config(database, view_type, data.get("config") or {}),
        position=data.get("position") or 0,
    )
    if not view.name:
        raise HttpError(400, "보기 이름이 필요합니다.")
    publish_workspace_event(database.workspace_id, "view", "created", view.id, user.id)
    return serialize_view(view)


@transaction.atomic
def update_view(user, view_id: int, data: dict[str, Any]) -> dict[str, Any]:
    view = get_view(user, view_id)
    if data.get("name") is not None:
        view.name = str(data["name"]).strip()
        if not view.name:
            raise HttpError(400, "보기 이름이 필요합니다.")
    next_type = view.type
    if data.get("type") is not None:
        if data["type"] not in View.Type.values:
            raise HttpError(400, "지원하지 않는 보기 타입입니다.")
        next_type = data["type"]
    next_config = view.config or {}
    if data.get("config") is not None:
        next_config = data["config"]
    view.type = next_type
    view.config = validate_view_config(view.database, next_type, next_config)
    if "filters" in data and data["filters"] is not None:
        view.filters = _normalize_filters(data["filters"])
    if "sorts" in data and data["sorts"] is not None:
        view.sorts = _normalize_sort_items(data["sorts"])
    if data.get("position") is not None:
        view.position = data["position"]
    view.save()
    publish_workspace_event(view.database.workspace_id, "view", "updated", view.id, user.id)
    return serialize_view(view)


@transaction.atomic
def delete_view(user, view_id: int) -> None:
    view = get_view(user, view_id)
    workspace_id = view.database.workspace_id
    deleted_id = view.id
    view.delete()
    publish_workspace_event(workspace_id, "view", "deleted", deleted_id, user.id)


def delete_record_object(record: Record) -> None:
    affected: set[tuple[int, int]] = set()
    for link in RelationLink.objects.filter(Q(from_record=record) | Q(to_record=record)):
        if link.from_record_id != record.id:
            affected.add((link.property_id, link.from_record_id))
    deleted_at = timezone.now()
    PropertyValue.objects.filter(record=record).update(deleted_at=deleted_at)
    RelationLink.objects.filter(Q(from_record=record) | Q(to_record=record)).update(
        deleted_at=deleted_at
    )
    props = {
        prop.id: prop
        for prop in Property.objects.filter(id__in={property_id for property_id, _record_id in affected})
    }
    for property_id, record_id in affected:
        prop = props.get(property_id)
        if prop is not None:
            _write_relation_ids(prop, record_id)
    soft_delete_blocks(list(record.blocks.values_list("id", flat=True)))
    record.delete()


@transaction.atomic
def create_record(user, database_id: int, data: dict[str, Any], source: str) -> dict[str, Any]:
    from workspace.access import require_content_write

    database = get_database(user, database_id)
    require_content_write(user, database=database)
    template = None
    if data.get("template_id") is not None:
        template = get_template(user, int(data["template_id"]))
        if template.database_id != database.id:
            raise HttpError(400, "템플릿이 데이터베이스와 맞지 않습니다.")
    title_source = data.get("title")
    if title_source is None and template is not None:
        title_source = template.title
    title = str(title_source or "").strip()
    if not title:
        raise HttpError(400, "제목이 필요합니다.")
    record = Record.objects.create(
        database=database,
        title=title,
        icon=str(data.get("icon") or ""),
        created_by=user,
        last_edited_by=user,
    )
    values = dict(template.values if template is not None else {})
    if data.get("values") is not None:
        values.update(data["values"])
    values[title_property(database).slug] = title
    apply_values(record, values)
    blocks = list(template.blocks if template is not None else [])
    if "blocks" in data and data.get("blocks") is not None:
        blocks = data["blocks"]
    create_block_tree(record, blocks, None)
    record.save(update_fields=["title", "last_edited_by", "updated_at"])
    after = _snapshot(record)
    log_activity(record, user, RecordActivity.Action.CREATED, {}, after, source)
    publish_workspace_event(database.workspace_id, "record", "created", record.id, user.id)
    return serialize_record(record, include_blocks=True)


@transaction.atomic
def update_record(user, record_id: int, data: dict[str, Any], source: str) -> dict[str, Any]:
    from workspace.access import require_content_write
    from workspace.blocksync import lock_owner, sync_blocks
    from workspace.revisions import BodyEdit

    record = get_record(user, record_id)
    require_content_write(user, database=record.database)
    if data.get("blocks") is not None:
        lock_owner(record)
    edit = BodyEdit(record, user)
    before = _snapshot(record)
    synced = None
    values = dict(data["values"]) if data.get("values") is not None else None
    if data.get("title") is not None:
        title = str(data["title"]).strip()
        if not title:
            raise HttpError(400, "제목은 비울 수 없습니다.")
        values = {} if values is None else values
        values[title_property(record.database).slug] = title
    if values is not None:
        apply_values(record, values)
    if data.get("blocks") is not None:
        synced = sync_blocks(
            record, data["blocks"], user, edit=edit, base_seq=data.get("base_seq")
        )
    if data.get("icon") is not None:
        record.icon = str(data["icon"])
    record.last_edited_by = user
    record.save(update_fields=["title", "last_edited_by", "updated_at"])
    after = _snapshot(record)
    log_activity(record, user, RecordActivity.Action.UPDATED, before, after, source)
    edit.finish(synced.created + synced.updated if synced is not None else None)
    publish_workspace_event(
        record.database.workspace_id, "record", "updated", record.id, user.id
    )
    return serialize_record(record, include_blocks=True)


@transaction.atomic
def delete_record(user, record_id: int) -> None:
    from workspace.access import require_content_write

    record = get_record(user, record_id)
    require_content_write(user, database=record.database)
    workspace_id = record.database.workspace_id
    deleted_id = record.id
    record.delete()
    publish_workspace_event(workspace_id, "record", "deleted", deleted_id, user.id)


def _block_parent(user, record: Record, parent_id: int | None) -> Block | None:
    if parent_id is None:
        return None
    parent = get_block(user, parent_id)
    if parent.record_id != record.id:
        raise HttpError(400, "부모 블록이 같은 레코드에 있어야 합니다.")
    return parent


def _block_parent_for_page(user, page: Page, parent_id: int | None) -> Block | None:
    if parent_id is None:
        return None
    parent = get_block(user, parent_id)
    if parent.page_id != page.id:
        raise HttpError(400, "부모 블록이 같은 페이지에 있어야 합니다.")
    return parent


def _reject_cycle(block: Block, parent: Block | None) -> None:
    current = parent
    while current is not None:
        if current.id == block.id:
            raise HttpError(400, "블록을 자신의 하위로 옮길 수 없습니다.")
        current = current.parent


@transaction.atomic
def create_block(user, record_id: int, data: dict[str, Any], source: str) -> dict[str, Any]:
    from workspace.access import require_content_write
    from workspace.revisions import BodyEdit

    record = get_record(user, record_id)
    require_content_write(user, database=record.database)
    edit = BodyEdit(record, user)
    before = _block_snapshot(record)
    block_type = _validate_block_type(str(data.get("type") or ""))
    content = validate_block_content(
        block_type, data.get("content") or {}, record.database.workspace_id
    )
    parent = _block_parent(user, record, data.get("parent_id"))
    assert_block_shape(block_type, None if parent is None else parent.type)
    edit.watch(content)
    block = Block.objects.create(
        record=record,
        parent=parent,
        type=block_type,
        content=content,
        position=data.get("position") or 0,
    )
    record.last_edited_by = user
    record.save(update_fields=["last_edited_by", "updated_at"])
    log_activity(
        record, user, RecordActivity.Action.UPDATED, before, _block_snapshot(record), source
    )
    publish_workspace_event(
        record.database.workspace_id, "block", "created", block.id, user.id
    )
    emit_block_collab(block, "created", user.id)
    edit.finish([block])
    return serialize_block(block)


@transaction.atomic
def update_block(user, block_id: int, data: dict[str, Any], source: str) -> dict[str, Any]:
    block = get_block(user, block_id)
    if block.record_id is None:
        return _update_page_block(user, block, data)
    from workspace.access import require_content_write
    from workspace.revisions import BodyEdit

    record = block.record
    require_content_write(user, database=record.database)
    edit = BodyEdit(record, user)
    before = _block_snapshot(record)
    if data.get("type") is not None:
        block.type = _validate_block_type(str(data["type"]))
    if data.get("content") is not None:
        block.content = validate_block_content(
            block.type, data["content"], record.database.workspace_id
        )
    if data.get("position") is not None:
        block.position = data["position"]
    if data.get("type") is not None and data.get("content") is None:
        block.content = validate_block_content(
            block.type, block.content or {}, record.database.workspace_id
        )
    if "parent_id" in data:
        parent = _block_parent(user, record, data.get("parent_id"))
        _reject_cycle(block, parent)
        block.parent = parent
    parent_type = None if block.parent_id is None else block.parent.type
    assert_block_shape(block.type, parent_type)
    if data.get("content") is not None or data.get("type") is not None:
        edit.watch(block.content)
    block.save()
    record.last_edited_by = user
    record.save(update_fields=["last_edited_by", "updated_at"])
    log_activity(
        record, user, RecordActivity.Action.UPDATED, before, _block_snapshot(record), source
    )
    publish_workspace_event(
        record.database.workspace_id, "block", "updated", block.id, user.id
    )
    emit_block_collab(block, "updated", user.id)
    edit.finish([block])
    return serialize_block(block)


def _update_page_block(user, block: Block, data: dict[str, Any]) -> dict[str, Any]:
    from workspace.access import require_content_write
    from workspace.revisions import BodyEdit

    page = block.page
    require_content_write(user, page=page)
    edit = BodyEdit(page, user)
    if data.get("type") is not None:
        block.type = _validate_block_type(str(data["type"]))
    if data.get("content") is not None:
        block.content = validate_block_content(block.type, data["content"], page.workspace_id)
    if data.get("position") is not None:
        block.position = data["position"]
    if data.get("type") is not None and data.get("content") is None:
        block.content = validate_block_content(block.type, block.content or {}, page.workspace_id)
    if "parent_id" in data:
        parent = _block_parent_for_page(user, page, data.get("parent_id"))
        _reject_cycle(block, parent)
        block.parent = parent
    parent_type = None if block.parent_id is None else block.parent.type
    assert_block_shape(block.type, parent_type)
    if data.get("content") is not None or data.get("type") is not None:
        edit.watch(block.content)
    block.save()
    publish_workspace_event(page.workspace_id, "block", "updated", block.id, user.id)
    emit_block_collab(block, "updated", user.id)
    edit.finish([block])
    return serialize_block(block)


@transaction.atomic
def delete_block(user, block_id: int, source: str) -> None:
    block = get_block(user, block_id)
    if block.record_id is None:
        from workspace.access import require_content_write
        from workspace.revisions import BodyEdit

        page = block.page
        require_content_write(user, page=page)
        edit = BodyEdit(page, user)
        deleted_id = block.id

        emit_block_collab(block, "deleted", user.id)
        soft_delete_blocks(_subtree_ids(block))
        edit.finish()
        publish_workspace_event(page.workspace_id, "block", "deleted", deleted_id, user.id)
        return
    from workspace.access import require_content_write
    from workspace.revisions import BodyEdit

    record = block.record
    require_content_write(user, database=record.database)
    edit = BodyEdit(record, user)
    before = _block_snapshot(record)

    emit_block_collab(block, "deleted", user.id)
    soft_delete_blocks(_subtree_ids(block))
    record.last_edited_by = user
    record.save(update_fields=["last_edited_by", "updated_at"])
    log_activity(
        record, user, RecordActivity.Action.UPDATED, before, _block_snapshot(record), source
    )
    edit.finish()
    publish_workspace_event(
        record.database.workspace_id, "block", "deleted", block_id, user.id
    )


def _properties_for_slug(databases: QuerySet[Database], slug: str) -> list[Property]:
    props = list(Property.objects.filter(database__in=databases, slug=slug))
    if not props:
        raise HttpError(400, f"속성 {slug}을 찾을 수 없습니다.")
    return props


def _resolve_filter_value(prop: Property, value: Any, user) -> Any:
    if prop.type != Property.Type.PEOPLE:
        return value
    if value == "me":
        return user.id
    if isinstance(value, list):
        return [user.id if item == "me" else item for item in value]
    return value


def _matching_record_ids(prop: Property, op: str, value: Any) -> QuerySet:
    base = Record.objects.filter(database_id=prop.database_id)
    stored = PropertyValue.objects.filter(property=prop)
    if op == "is_empty":
        return base.exclude(id__in=stored.values("record_id"))
    if op == "neq":
        matched = _matching_record_ids(prop, "eq", value)
        return base.exclude(id__in=matched.values("id"))
    if prop.type in TEXT_TYPES or prop.type in {Property.Type.SELECT, Property.Type.STATUS}:
        if prop.type in {Property.Type.SELECT, Property.Type.STATUS} and op in {"eq", "in"}:
            if op == "eq":
                name = canonical_option_name(prop, value)
                return base.filter(id__in=stored.filter(text_value=name).values("record_id"))
            if not isinstance(value, list):
                raise HttpError(400, "in 연산의 값은 목록이어야 합니다.")
            names = [canonical_option_name(prop, item) for item in value]
            return base.filter(id__in=stored.filter(text_value__in=names).values("record_id"))
        if op == "eq":
            return base.filter(id__in=stored.filter(text_value=str(value)).values("record_id"))
        if op == "contains":
            return base.filter(
                id__in=stored.filter(text_value__icontains=str(value)).values("record_id")
            )
        if op == "in":
            if not isinstance(value, list):
                raise HttpError(400, "in 연산의 값은 목록이어야 합니다.")
            return base.filter(
                id__in=stored.filter(text_value__in=[str(item) for item in value]).values(
                    "record_id"
                )
            )
        raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
    if prop.type == Property.Type.NUMBER:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise HttpError(400, "숫자 형식이 올바르지 않습니다.") from None
        lookup = {
            "eq": "number_value",
            "gt": "number_value__gt",
            "gte": "number_value__gte",
            "lt": "number_value__lt",
            "lte": "number_value__lte",
        }.get(op)
        if lookup is None:
            raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
        return base.filter(id__in=stored.filter(**{lookup: number}).values("record_id"))
    if prop.type == Property.Type.DATE:
        moment = _parse_datetime(value)
        lookup = {
            "eq": "date_start",
            "gt": "date_start__gt",
            "gte": "date_start__gte",
            "lt": "date_start__lt",
            "lte": "date_start__lte",
        }.get(op)
        if lookup is None:
            raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
        return base.filter(id__in=stored.filter(**{lookup: moment}).values("record_id"))
    if prop.type == Property.Type.CHECKBOX:
        if op != "eq" or not isinstance(value, bool):
            raise HttpError(400, "체크박스는 eq와 true/false만 지원합니다.")
        return base.filter(
            id__in=stored.filter(checkbox_value=value).values("record_id")
        )
    if prop.type == Property.Type.MULTI_SELECT:
        if op == "eq":
            name = canonical_option_name(prop, value)
            return base.filter(id__in=stored.filter(json_value__contains=[name]).values("record_id"))
        if op == "contains":
            return base.filter(
                id__in=stored.filter(text_value__icontains=str(value)).values("record_id")
            )
        if op == "in":
            if not isinstance(value, list):
                raise HttpError(400, "in 연산의 값은 목록이어야 합니다.")
            query = Q()
            for item in value:
                query |= Q(json_value__contains=[canonical_option_name(prop, item)])
            return base.filter(id__in=stored.filter(query).values("record_id"))
        raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
    if prop.type == Property.Type.PEOPLE:
        if op == "eq":
            if isinstance(value, bool) or not isinstance(value, int):
                raise HttpError(400, "사람 필터 값은 사용자 id여야 합니다.")
            return base.filter(
                id__in=stored.filter(json_value__contains=[value]).values("record_id")
            )
        if op == "in":
            if not isinstance(value, list):
                raise HttpError(400, "in 연산의 값은 목록이어야 합니다.")
            query = Q()
            for item in value:
                if isinstance(item, bool) or not isinstance(item, int):
                    raise HttpError(400, "사람 필터 값은 사용자 id여야 합니다.")
                query |= Q(json_value__contains=[item])
            return base.filter(id__in=stored.filter(query).values("record_id"))
        raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
    if prop.type == Property.Type.RELATION:
        if op != "eq" or isinstance(value, bool) or not isinstance(value, int):
            raise HttpError(400, "관계 필터는 레코드 id의 eq만 지원합니다.")
        linked = RelationLink.objects.filter(
            property=prop, to_record_id=value
        ).values("from_record_id")
        return base.filter(id__in=linked)
    if prop.type == Property.Type.FILES:
        if op != "contains":
            raise HttpError(400, "파일 속성은 contains만 지원합니다.")
        return base.filter(
            id__in=stored.filter(text_value__icontains=str(value)).values("record_id")
        )
    raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")


def _apply_system_filter(qs: QuerySet, slug: str, op: str, value: Any, user) -> QuerySet:
    if slug in SYSTEM_USER_FIELDS:
        if value == "me":
            value = user.id
        elif isinstance(value, list):
            value = [user.id if item == "me" else item for item in value]
        field = f"{slug}_id"
        if op == "is_empty":
            return qs.filter(**{f"{field}__isnull": True})
        if op == "eq":
            if isinstance(value, bool) or not isinstance(value, int):
                raise HttpError(400, "작성자 필터 값은 사용자 id여야 합니다.")
            return qs.filter(**{field: value})
        if op == "neq":
            if isinstance(value, bool) or not isinstance(value, int):
                raise HttpError(400, "작성자 필터 값은 사용자 id여야 합니다.")
            return qs.exclude(**{field: value})
        if op == "in":
            if not isinstance(value, list):
                raise HttpError(400, "in 연산의 값은 목록이어야 합니다.")
            for item in value:
                if isinstance(item, bool) or not isinstance(item, int):
                    raise HttpError(400, "작성자 필터 값은 사용자 id여야 합니다.")
            return qs.filter(**{f"{field}__in": value})
        raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
    if op == "is_empty":
        return qs.none()
    if op == "neq":
        return qs.exclude(**{slug: _parse_datetime(value)})
    lookup = {
        "eq": slug,
        "gt": f"{slug}__gt",
        "gte": f"{slug}__gte",
        "lt": f"{slug}__lt",
        "lte": f"{slug}__lte",
    }.get(op)
    if lookup is None:
        raise HttpError(400, "이 속성에는 쓸 수 없는 연산입니다.")
    return qs.filter(**{lookup: _parse_datetime(value)})


def _apply_one_filter(qs: QuerySet, databases: QuerySet, item: dict, user) -> QuerySet:
    slug = item["property"]
    if slug in SYSTEM_FIELDS:
        return _apply_system_filter(qs, slug, item["op"], item.get("value"), user)
    props = _properties_for_slug(databases, slug)
    query = Q()
    for prop in props:
        value = _resolve_filter_value(prop, item.get("value"), user)
        query |= Q(id__in=_matching_record_ids(prop, item["op"], value).values("id"))
    return qs.filter(id__in=Record.objects.filter(query).values("id"))


def _apply_filters(qs: QuerySet, databases: QuerySet, filters: list[dict], user) -> QuerySet:
    for item in filters:
        qs = _apply_one_filter(qs, databases, item, user)
    return qs


def _apply_filter_tree(qs: QuerySet, databases: QuerySet, node: Any, user) -> QuerySet:
    if node is None or node == [] or node == {}:
        return qs
    if isinstance(node, list):
        for item in node:
            qs = _apply_filter_tree(qs, databases, item, user)
        return qs
    if isinstance(node, dict) and "filters" in node and "property" not in node:
        if node.get("op") == "and":
            for child in node["filters"]:
                qs = _apply_filter_tree(qs, databases, child, user)
            return qs
        combined = Q()
        for child in node["filters"]:
            matched = _apply_filter_tree(
                Record.objects.filter(database__in=databases),
                databases,
                child,
                user,
            )
            combined |= Q(id__in=matched.values("id"))
        return qs.filter(combined)
    return _apply_one_filter(qs, databases, node, user)


def _sort_field(props: list[Property]) -> str:
    types = {prop.type for prop in props}
    if types <= {Property.Type.NUMBER}:
        return "number_value"
    if types <= {Property.Type.DATE}:
        return "date_start"
    if types <= {Property.Type.CHECKBOX}:
        return "checkbox_value"
    return "text_value"


def query_records(user, data: dict[str, Any]) -> dict[str, Any]:
    page = int(data.get("page") or 1)
    page_size = int(data.get("page_size") or 20)
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise HttpError(400, "페이지 값이 올바르지 않습니다.")

    databases = accessible_databases(user)
    view_filters: Any = []
    view_sorts: list[dict] = []
    if data.get("view_id"):
        view = get_view(user, int(data["view_id"]))
        databases = databases.filter(id=view.database_id)
        view_filters = _normalize_filters(view.filters)
        view_sorts = _normalize_sort_items(view.sorts)
    if data.get("database_id"):
        database = get_database(user, int(data["database_id"]))
        if data.get("view_id") and view.database_id != database.id:
            raise HttpError(400, "보기가 데이터베이스와 맞지 않습니다.")
        databases = databases.filter(id=database.id)
    if data.get("database_slug"):
        databases = databases.filter(slug=str(data["database_slug"]))
        if not databases.exists():
            raise HttpError(404, "데이터베이스를 찾을 수 없습니다.")
    if data.get("workspace_id"):
        get_membership(user, int(data["workspace_id"]))
        databases = databases.filter(workspace_id=int(data["workspace_id"]))

    qs = Record.objects.filter(database__in=databases).select_related("database")
    keyword = (data.get("q") or "").strip()
    if keyword:
        value_ids = PropertyValue.objects.filter(
            record__database__in=databases,
            text_value__icontains=keyword,
        ).values("record_id")
        block_ids = Block.objects.filter(
            plain_text__icontains=keyword, record__database__in=databases
        ).values("record_id")
        qs = qs.filter(
            Q(title__icontains=keyword) | Q(id__in=value_ids) | Q(id__in=block_ids)
        )
    qs = _apply_filter_tree(qs, databases, view_filters, user)
    qs = _apply_filter_tree(qs, databases, _normalize_filters(data.get("filters")), user)
    sorts = _normalize_sort_items(data.get("sorts")) or view_sorts
    order: list[str] = []
    for index, item in enumerate(sorts):
        if item["property"] in SYSTEM_FIELDS:
            field = item["property"]
            if field in SYSTEM_USER_FIELDS:
                field = f"{field}_id"
            prefix = "" if item["direction"] == "asc" else "-"
            order.append(f"{prefix}{field}")
            continue
        props = _properties_for_slug(databases, item["property"])
        annotation = f"_sort_{index}"
        subquery = Subquery(
            PropertyValue.objects.filter(
                record=OuterRef("pk"),
                property__slug=item["property"],
            ).values(_sort_field(props))[:1]
        )
        qs = qs.annotate(**{annotation: subquery})
        prefix = "" if item["direction"] == "asc" else "-"
        order.append(f"{prefix}{annotation}")
    order.append("-created_at")
    qs = qs.order_by(*order)
    total = qs.count()
    start = (page - 1) * page_size
    rows = list(qs[start : start + page_size])
    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "data": serialize_record_page(rows),
    }


def _author_name(user) -> str:
    if user is None:
        return ""
    return user.name or ""


def serialize_activity(activity: RecordActivity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "action": activity.action,
        "source": activity.source,
        "actor_id": activity.actor_id,
        "actor_name": _author_name(activity.actor),
        "changes": activity.changes or {},
        "created_at": activity.created_at,
    }


def list_activities(user, record_id: int) -> list[dict[str, Any]]:
    record = get_record(user, record_id)
    rows = (
        RecordActivity.objects.filter(record=record)
        .select_related("actor")
        .order_by("-id")[:ACTIVITY_LIMIT]
    )
    return [serialize_activity(row) for row in rows]


def serialize_comment(comment: RecordComment) -> dict[str, Any]:
    return {
        "id": comment.id,
        "record_id": comment.record_id,
        "parent_id": comment.parent_id,
        "author_id": comment.author_id,
        "author_name": _author_name(comment.author),
        "body": comment.body,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
    }


def get_comment(user, comment_id: int) -> RecordComment:
    comment = (
        RecordComment.objects.select_related(
            "record", "record__database", "record__database__workspace", "author"
        )
        .filter(id=comment_id)
        .first()
    )
    if comment is None:
        raise HttpError(404, "댓글을 찾을 수 없습니다.")
    if not _membership_exists(user, comment.record.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return comment


def list_comments(user, record_id: int) -> list[dict[str, Any]]:
    record = get_record(user, record_id)
    rows = (
        RecordComment.objects.filter(record=record)
        .select_related("author")
        .order_by("id")
    )
    return [serialize_comment(row) for row in rows]


@transaction.atomic
def create_comment(user, record_id: int, data: dict[str, Any]) -> dict[str, Any]:
    record = get_record(user, record_id)
    body = str(data.get("body") or "").strip()
    if not body:
        raise HttpError(400, "댓글 내용이 필요합니다.")
    parent = None
    if data.get("parent_id") is not None:
        parent = get_comment(user, int(data["parent_id"]))
        if parent.record_id != record.id:
            raise HttpError(400, "답글은 같은 레코드의 댓글에만 달 수 있습니다.")
        if parent.parent_id is not None:
            raise HttpError(400, "답글에는 다시 답글을 달 수 없습니다.")
    comment = RecordComment.objects.create(
        record=record,
        author=user,
        parent=parent,
        body=body,
    )
    publish_workspace_event(
        record.database.workspace_id, "comment", "created", comment.id, user.id
    )
    return serialize_comment(comment)


@transaction.atomic
def delete_comment(user, comment_id: int) -> None:
    comment = get_comment(user, comment_id)
    membership = get_membership(user, comment.record.database.workspace_id)
    if comment.author_id != user.id and membership.role not in {
        WorkspaceMember.Role.OWNER,
        WorkspaceMember.Role.ADMIN,
    }:
        raise HttpError(403, "댓글을 삭제할 권한이 없습니다.")
    for reply in RecordComment.objects.filter(parent=comment):
        reply.delete()
    workspace_id = comment.record.database.workspace_id
    deleted_id = comment.id
    comment.delete()
    publish_workspace_event(workspace_id, "comment", "deleted", deleted_id, user.id)


def serialize_template(template: DatabaseTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "database_id": template.database_id,
        "name": template.name,
        "title": template.title,
        "values": template.values or {},
        "blocks": template.blocks or [],
        "position": template.position,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def get_template(user, template_id: int) -> DatabaseTemplate:
    template = (
        DatabaseTemplate.objects.select_related("database", "database__workspace")
        .filter(id=template_id)
        .first()
    )
    if template is None:
        raise HttpError(404, "템플릿을 찾을 수 없습니다.")
    if not _membership_exists(user, template.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return template


def _clean_template_payload(database: Database, data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    if not partial or data.get("name") is not None:
        name = str(data.get("name") or "").strip()
        if not name:
            raise HttpError(400, "템플릿 이름이 필요합니다.")
        cleaned["name"] = name
    if not partial or "title" in data:
        cleaned["title"] = str(data.get("title") or "")
    if not partial or data.get("values") is not None:
        values = data.get("values") or {}
        if not isinstance(values, dict):
            raise HttpError(400, "템플릿 값은 객체여야 합니다.")
        known = set(database.properties.values_list("slug", flat=True))
        unknown = set(values) - known
        if unknown:
            raise HttpError(400, f"속성 {sorted(unknown)[0]}을 찾을 수 없습니다.")
        cleaned["values"] = values
    if not partial or data.get("blocks") is not None:
        blocks = data.get("blocks") or []
        if not isinstance(blocks, list):
            raise HttpError(400, "템플릿 블록은 목록이어야 합니다.")
        _validate_block_tree(blocks, database.workspace_id)
        cleaned["blocks"] = blocks
    if not partial or data.get("position") is not None:
        cleaned["position"] = int(data.get("position") or 0)
    return cleaned


def _validate_block_tree(blocks: list, workspace_id: int, parent_type: str | None = None) -> None:
    for data in blocks:
        if not isinstance(data, dict):
            raise HttpError(400, "블록 내용은 객체여야 합니다.")
        block_type = _validate_block_type(str(data.get("type") or ""))
        assert_block_shape(block_type, parent_type)
        validate_block_content(block_type, data.get("content") or {}, workspace_id)
        children = data.get("children") or []
        if not isinstance(children, list):
            raise HttpError(400, "하위 블록은 목록이어야 합니다.")
        _validate_block_tree(children, workspace_id, block_type)


def list_templates(user, database_id: int) -> list[dict[str, Any]]:
    database = get_database(user, database_id)
    rows = database.templates.order_by("position", "id")
    return [serialize_template(row) for row in rows]


@transaction.atomic
def create_template(user, database_id: int, data: dict[str, Any]) -> dict[str, Any]:
    database = get_database(user, database_id)
    cleaned = _clean_template_payload(database, data, partial=False)
    template = DatabaseTemplate.objects.create(database=database, **cleaned)
    publish_workspace_event(database.workspace_id, "template", "created", template.id, user.id)
    return serialize_template(template)


@transaction.atomic
def update_template(user, template_id: int, data: dict[str, Any]) -> dict[str, Any]:
    template = get_template(user, template_id)
    cleaned = _clean_template_payload(template.database, data, partial=True)
    for key, value in cleaned.items():
        setattr(template, key, value)
    template.save()
    publish_workspace_event(
        template.database.workspace_id, "template", "updated", template.id, user.id
    )
    return serialize_template(template)


@transaction.atomic
def delete_template(user, template_id: int) -> None:
    template = get_template(user, template_id)
    workspace_id = template.database.workspace_id
    deleted_id = template.id
    template.delete()
    publish_workspace_event(workspace_id, "template", "deleted", deleted_id, user.id)


def list_trash(user, workspace_id: int) -> list[dict[str, Any]]:
    get_membership(user, workspace_id)
    rows = (
        Record.all_objects.filter(
            deleted_at__isnull=False,
            database__workspace_id=workspace_id,
            database__deleted_at__isnull=True,
        )
        .select_related("database")
        .order_by("-deleted_at", "-id")
    )
    items = [
        {
            "kind": "record",
            "id": row.id,
            "title": row.title,
            "icon": row.icon,
            "database_id": row.database_id,
            "database_slug": row.database.slug,
            "database_name": row.database.name,
            "page_kind": None,
            "deleted_at": row.deleted_at,
        }
        for row in rows
    ]
    from workspace.tree import trash_pages

    items.extend(trash_pages(workspace_id))
    items.sort(key=lambda item: (item["deleted_at"], item["id"]), reverse=True)
    return items[:TRASH_LIMIT]


@transaction.atomic
def restore_record(user, record_id: int) -> dict[str, Any]:
    record = (
        Record.all_objects.select_related("database", "database__workspace")
        .filter(id=record_id, deleted_at__isnull=False)
        .first()
    )
    if record is None or record.database.deleted_at is not None:
        raise HttpError(404, "휴지통에서 레코드를 찾을 수 없습니다.")
    if not _membership_exists(user, record.database.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    from workspace.access import require_content_write

    require_content_write(user, database=record.database)
    record.restore()
    publish_workspace_event(
        record.database.workspace_id, "record", "restored", record.id, user.id
    )
    return serialize_record(record, include_blocks=True)


def _raw_values(record: Record) -> dict[str, Any]:
    values: dict[str, Any] = {}
    stored = (
        PropertyValue.objects.filter(record=record)
        .select_related("property")
        .order_by("property__position", "property_id")
    )
    for item in stored:
        if item.property.type == Property.Type.RELATION:
            raw_ids = item.json_value if isinstance(item.json_value, list) else []
            values[item.property.slug] = [
                record_id
                for record_id in raw_ids
                if isinstance(record_id, int) and not isinstance(record_id, bool)
            ]
        else:
            values[item.property.slug] = export_value(item)
    return values


def _copy_record_blocks(source: Record, target: Record) -> None:
    blocks = list(source.blocks.order_by("position", "id"))

    def _copy(parent_id: int | None, new_parent: Block | None) -> None:
        for block in blocks:
            if block.parent_id != parent_id:
                continue
            created = Block.objects.create(
                record=target,
                parent=new_parent,
                type=block.type,
                content=block.content or {},
                position=block.position,
            )
            _copy(block.id, created)

    _copy(None, None)


@transaction.atomic
def duplicate_record(user, record_id: int, source: str) -> dict[str, Any]:
    from workspace.access import require_content_write

    original = get_record(user, record_id)
    require_content_write(user, database=original.database)
    title = f"{original.title} 복사"[:300]
    record = Record.objects.create(
        database=original.database,
        title=title,
        icon=original.icon,
        created_by=user,
        last_edited_by=user,
    )
    values = _raw_values(original)
    values[title_property(original.database).slug] = title
    apply_values(record, values)
    _copy_record_blocks(original, record)
    record.save(update_fields=["title", "last_edited_by", "updated_at"])
    log_activity(record, user, RecordActivity.Action.CREATED, {}, _snapshot(record), source)
    publish_workspace_event(original.database.workspace_id, "record", "created", record.id, user.id)
    return serialize_record(record, include_blocks=True)


def _page_window(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise HttpError(400, "페이지 값이 올바르지 않습니다.")
    return page, page_size


def search_workspace(user, data: dict[str, Any]) -> dict[str, Any]:
    page, page_size = _page_window(int(data.get("page") or 1), int(data.get("page_size") or 20))
    workspace_id = int(data["workspace_id"])
    get_membership(user, workspace_id)
    keyword = str(data.get("q") or "").strip()
    if not keyword:
        raise HttpError(400, "검색어가 필요합니다.")
    databases = accessible_databases(user).filter(workspace_id=workspace_id)
    records = Record.objects.filter(database__in=databases).select_related("database")
    value_ids = PropertyValue.objects.filter(
        record__database__in=databases,
        text_value__icontains=keyword,
    ).values("record_id")
    block_ids = Block.objects.filter(
        plain_text__icontains=keyword, record__database__in=databases
    ).values("record_id")
    records = records.filter(
        Q(title__icontains=keyword) | Q(id__in=value_ids) | Q(id__in=block_ids)
    ).order_by("-updated_at", "-id")
    from workspace.models import Page

    page_block_ids = Block.objects.filter(
        plain_text__icontains=keyword,
        page__workspace_id=workspace_id,
        page__kind=Page.Kind.DOCUMENT,
    ).values("page_id")
    documents = Page.objects.filter(workspace_id=workspace_id, kind=Page.Kind.DOCUMENT).filter(
        Q(name__icontains=keyword) | Q(id__in=page_block_ids)
    ).order_by("-updated_at", "-id")
    need = page * page_size
    record_rows = list(records[:need])
    document_rows = list(documents[:need])
    hits: list[dict[str, Any]] = [
        {
            "kind": "record",
            "id": row.id,
            "title": row.title,
            "database_id": row.database_id,
            "database_slug": row.database.slug,
            "updated_at": row.updated_at,
        }
        for row in record_rows
    ]
    hits.extend(
        {
            "kind": "page",
            "id": row.id,
            "title": row.name,
            "database_id": None,
            "database_slug": "",
            "updated_at": row.updated_at,
        }
        for row in document_rows
    )
    hits.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
    start = (page - 1) * page_size
    window = hits[start : start + page_size]
    for item in window:
        item.pop("updated_at", None)
    return {
        "count": records.count() + documents.count(),
        "page": page,
        "page_size": page_size,
        "data": window,
    }
