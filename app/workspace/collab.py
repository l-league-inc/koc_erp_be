"""문서방 편집입니다. AppFlowy-Cloud의 문서 동기화와 커서 알림을 JSON으로 나눈 형태입니다."""

import time
from typing import Any
from urllib.parse import parse_qs

from django.core.cache import cache
from ninja.errors import HttpError

from workspace.models import CollabEvent, Page, Record
from workspace.tree import create_page_block, get_page, list_page_blocks
from workspace.utils import create_block, delete_block, get_block, get_record, serialize_block, update_block

PRESENCE_TTL = 45


def room_key(target: str, target_id: int) -> str:
    return f"collab-presence:{target}:{target_id}"


def parse_since(query_string: bytes | str | None) -> int | None:
    if not query_string:
        return None
    if isinstance(query_string, bytes):
        query_string = query_string.decode()
    raw = (parse_qs(query_string).get("since") or [None])[0]
    if raw is None or not str(raw).isdigit():
        return None
    return int(raw)


def _current_seq(target: str, target_id: int) -> int:
    if target == "record":
        seq = Record.objects.filter(id=target_id).values_list("collab_seq", flat=True).first()
    else:
        seq = Page.objects.filter(id=target_id).values_list("collab_seq", flat=True).first()
    return int(seq or 0)


def _event_body(event: CollabEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "action": event.action,
        "actor_id": event.actor_id,
        "block_id": event.block_id,
        "block": event.block,
    }


def opening_payload(
    user,
    workspace_id: int,
    target: str,
    target_id: int,
    since: int | None,
) -> dict[str, Any] | None:
    blocks = document_blocks(user, workspace_id, target, target_id)
    if blocks is None:
        return None
    seq = _current_seq(target, target_id)
    full = {"type": "sync", "target": target, "target_id": target_id, "seq": seq, "blocks": blocks}
    if since is None or since > seq:
        return full
    if since == seq:
        return {"type": "catchup", "target": target, "target_id": target_id, "seq": seq, "events": []}
    stored = CollabEvent.objects.filter(seq__gt=since, seq__lte=seq)
    if target == "record":
        stored = stored.filter(record_id=target_id)
    else:
        stored = stored.filter(page_id=target_id)
    events = list(stored.order_by("seq"))
    expected = list(range(since + 1, seq + 1))
    if [event.seq for event in events] != expected or any(event.action == "reload" for event in events):
        return full
    return {
        "type": "catchup",
        "target": target,
        "target_id": target_id,
        "seq": seq,
        "events": [_event_body(event) for event in events],
    }


def document_blocks(user, workspace_id: int, target: str, target_id: int) -> list[dict[str, Any]] | None:
    if target == "record":
        record = get_record(user, target_id)
        if record.database.workspace_id != workspace_id:
            return None
        return [serialize_block(block) for block in record.blocks.order_by("position", "id")]
    if target != "page":
        return None
    page = get_page(user, target_id)
    if page.workspace_id != workspace_id or page.kind != Page.Kind.DOCUMENT:
        return None
    return list_page_blocks(user, target_id)


def _live(raw: Any) -> dict[str, dict[str, Any]]:
    now = time.time()
    if not isinstance(raw, dict):
        return {}
    return {
        key: item
        for key, item in raw.items()
        if isinstance(item, dict) and now - float(item.get("seen_at") or 0) < PRESENCE_TTL
    }


def read_presence(target: str, target_id: int) -> dict[str, dict[str, Any]]:
    live = _live(cache.get(room_key(target, target_id)))
    cache.set(room_key(target, target_id), live, 60 * 60 * 24)
    return live


def write_presence(target: str, target_id: int, people: dict[str, dict[str, Any]]) -> None:
    cache.set(room_key(target, target_id), _live(people), 60 * 60 * 24)


def presence_payload(people: dict[str, dict[str, Any]]) -> dict[str, Any]:
    users = [
        {
            "presence_id": item["presence_id"],
            "user_id": item["user_id"],
            "name": item.get("name") or "",
            "cursor": item.get("cursor"),
            "selection": item.get("selection"),
        }
        for item in people.values()
    ]
    return {"type": "presence", "users": users}


def _cursor(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HttpError(400, "커서 형식이 올바르지 않습니다.")
    block_id = value.get("block_id")
    offset = value.get("offset")
    if isinstance(block_id, bool) or not isinstance(block_id, int):
        raise HttpError(400, "커서 블록은 id여야 합니다.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise HttpError(400, "커서 위치는 0 이상의 정수여야 합니다.")
    return {"block_id": block_id, "offset": offset}


def clean_awareness(data: dict[str, Any]) -> tuple[dict[str, int] | None, dict[str, Any] | None]:
    cursor = _cursor(data.get("cursor"))
    selection = data.get("selection")
    if selection is not None:
        if not isinstance(selection, dict):
            raise HttpError(400, "선택 영역 형식이 올바르지 않습니다.")
        selection = {"anchor": _cursor(selection.get("anchor")), "focus": _cursor(selection.get("focus"))}
    return cursor, selection


def apply_collab_op(user, target: str, target_id: int, data: dict[str, Any]) -> None:
    action = data.get("action")
    if action == "create":
        block = data.get("block")
        if not isinstance(block, dict):
            raise HttpError(400, "블록 내용이 필요합니다.")
        if target == "record":
            create_block(user, target_id, block, "user")
        else:
            create_page_block(user, target_id, block)
        return
    block_id = data.get("block_id")
    if isinstance(block_id, bool) or not isinstance(block_id, int):
        raise HttpError(400, "블록 id가 필요합니다.")
    block = get_block(user, block_id)
    if target == "record" and block.record_id != target_id:
        raise HttpError(400, "이 문서의 블록이 아닙니다.")
    if target == "page" and block.page_id != target_id:
        raise HttpError(400, "이 문서의 블록이 아닙니다.")
    if action == "update":
        patch = data.get("block")
        if not isinstance(patch, dict):
            raise HttpError(400, "수정할 블록 내용이 필요합니다.")
        update_block(user, block_id, patch, "user")
        return
    if action == "delete":
        delete_block(user, block_id, "user")
        return
    raise HttpError(400, "지원하지 않는 편집 동작입니다.")


def touch_presence(
    target: str,
    target_id: int,
    *,
    channel_name: str,
    presence_id: str,
    user_id: int,
    name: str,
    cursor: dict[str, int] | None = None,
    selection: dict[str, Any] | None = None,
    keep_cursor: bool = False,
) -> dict[str, dict[str, Any]]:
    people = read_presence(target, target_id)
    current = people.get(channel_name, {})
    people[channel_name] = {
        "presence_id": presence_id,
        "user_id": user_id,
        "name": name,
        "cursor": current.get("cursor") if keep_cursor else cursor,
        "selection": current.get("selection") if keep_cursor else selection,
        "seen_at": time.time(),
    }
    write_presence(target, target_id, people)
    return people


def drop_presence(target: str, target_id: int, channel_name: str) -> dict[str, dict[str, Any]]:
    people = read_presence(target, target_id)
    people.pop(channel_name, None)
    write_presence(target, target_id, people)
    return people
