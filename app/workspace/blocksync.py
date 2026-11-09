"""본문 블록을 트리째 받아 id 기준으로 바뀐 블록만 반영합니다.

요청 트리에서 `id`가 있는 블록은 같은 블록으로 보고 달라진 것만 고칩니다.
`id`가 없으면 새 블록이고, 서버에는 있는데 트리에 없는 블록은 지웁니다.
블록 id가 유지되므로 댓글, 멘션 알림, 커서가 깨지지 않습니다.
"""

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from workspace.events import publish_collab_events, publish_workspace_event
from workspace.models import Block, Page, Record
from workspace.revisions import BodyEdit
from workspace.text import extract_plain_text

POSITION_STEP = 1024
RELOAD_THRESHOLD = 30
CONFLICT_MESSAGE = "다른 곳에서 문서가 바뀌었습니다. 다시 불러온 뒤 저장해 주세요."


@dataclass
class _Node:
    type: str
    content: dict[str, Any]
    block: Block | None
    parent: "_Node | None"
    depth: int
    fresh: bool = False
    position: int = 0
    children: list["_Node"] = field(default_factory=list)


@dataclass
class SyncResult:
    seq: int
    ids: list[int]
    created: list[Block]
    updated: list[Block]
    deleted_ids: list[int]

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deleted_ids)


def lock_owner(owner: Record | Page) -> int:
    """문서 행을 잠그고 현재 `collab_seq`를 돌려줍니다."""
    model = Record if isinstance(owner, Record) else Page
    return model.objects.select_for_update().get(pk=owner.pk).collab_seq


def _longest_increasing(stored: list[int | None]) -> set[int]:
    tails: list[int] = []
    tail_index: list[int] = []
    previous: dict[int, int | None] = {}
    for index, value in enumerate(stored):
        if value is None:
            continue
        slot = bisect_left(tails, value)
        if slot == len(tails):
            tails.append(value)
            tail_index.append(index)
        else:
            tails[slot] = value
            tail_index[slot] = index
        previous[index] = tail_index[slot - 1] if slot > 0 else None
    keep: set[int] = set()
    cursor = tail_index[-1] if tail_index else None
    while cursor is not None:
        keep.add(cursor)
        cursor = previous[cursor]
    return keep


def assign_positions(stored: list[int | None]) -> list[int]:
    """형제 순서대로 `position`을 정합니다.

    이미 순서가 맞는 블록은 값을 그대로 두고, 새로 끼는 블록만 이웃 사이 값을 받습니다.
    사이가 없으면 형제 전체를 간격을 두고 다시 매깁니다.
    """
    count = len(stored)
    keep = _longest_increasing(stored)
    result = [0] * count
    lower = -1
    index = 0
    while index < count:
        if index in keep:
            result[index] = lower = int(stored[index])  # type: ignore[arg-type]
            index += 1
            continue
        end = index
        while end < count and end not in keep:
            end += 1
        run = end - index
        if end == count:
            base = lower if lower >= 0 else -POSITION_STEP
            for offset in range(run):
                result[index + offset] = base + POSITION_STEP * (offset + 1)
        else:
            upper = int(stored[end])  # type: ignore[arg-type]
            room = upper - lower
            if room < run + 1:
                return [slot * POSITION_STEP for slot in range(count)]
            for offset in range(run):
                result[index + offset] = lower + room * (offset + 1) // (run + 1)
        index = end
    return result


def _flatten(
    tree: list[dict[str, Any]],
    existing: dict[int, Block],
    workspace_id: int,
    edit: BodyEdit | None,
) -> list[_Node]:
    from workspace.utils import _validate_block_type, assert_block_shape, validate_block_content

    nodes: list[_Node] = []
    seen: set[int] = set()

    def walk(items: list[dict[str, Any]], parent: _Node | None) -> None:
        for data in items or []:
            block_type = _validate_block_type(str(data.get("type") or ""))
            assert_block_shape(block_type, None if parent is None else parent.type)
            block: Block | None = None
            block_id = data.get("id")
            if block_id is not None:
                if isinstance(block_id, bool) or not isinstance(block_id, int):
                    raise HttpError(400, "블록 id는 정수여야 합니다.")
                block = existing.get(block_id)
                if block is None:
                    raise HttpError(400, "이 문서의 블록이 아닙니다.")
                if block_id in seen:
                    raise HttpError(400, "같은 블록 id가 두 번 있습니다.")
                seen.add(block_id)
            raw = data.get("content") or {}
            if block is not None and block.type == block_type and raw == (block.content or {}):
                content = block.content or {}
            else:
                content = validate_block_content(block_type, raw, workspace_id)
                if edit is not None:
                    edit.watch(content)
            node = _Node(
                type=block_type,
                content=content,
                block=block,
                parent=parent,
                depth=0 if parent is None else parent.depth + 1,
                fresh=block is None,
            )
            nodes.append(node)
            if parent is not None:
                parent.children.append(node)
            walk(data.get("children") or [], node)

    walk(tree, None)
    return nodes


def _stored_position(node: _Node) -> int | None:
    block = node.block
    if block is None:
        return None
    if node.parent is None:
        return block.position if block.parent_id is None else None
    parent_block = node.parent.block
    if parent_block is None:
        return None
    return block.position if block.parent_id == parent_block.id else None


def _assign_all_positions(nodes: list[_Node]) -> None:
    groups: dict[int | None, list[_Node]] = {}
    for node in nodes:
        groups.setdefault(None if node.parent is None else id(node.parent), []).append(node)
    for siblings in groups.values():
        positions = assign_positions([_stored_position(node) for node in siblings])
        for node, position in zip(siblings, positions):
            node.position = position


def sync_blocks(
    owner: Record | Page,
    tree: list[dict[str, Any]],
    actor,
    *,
    edit: BodyEdit | None = None,
    base_seq: int | None = None,
) -> SyncResult:
    """`tree`를 `owner` 본문으로 맞춥니다. 호출하는 쪽이 트랜잭션과 권한을 맡습니다."""
    is_record = isinstance(owner, Record)
    workspace_id = owner.database.workspace_id if is_record else owner.workspace_id
    current_seq = lock_owner(owner)
    if base_seq is not None and base_seq != current_seq:
        raise HttpError(409, CONFLICT_MESSAGE)

    existing = {block.id: block for block in owner.blocks.all()}
    nodes = _flatten(tree, existing, workspace_id, edit)
    kept = {node.block.id for node in nodes if node.block is not None}
    removed_ids = [block_id for block_id in existing if block_id not in kept]
    _assign_all_positions(nodes)
    now = timezone.now()

    created: list[Block] = []
    fresh = [node for node in nodes if node.fresh]
    for depth in sorted({node.depth for node in fresh}):
        level = [node for node in fresh if node.depth == depth]
        rows = [
            Block(
                record=owner if is_record else None,
                page=None if is_record else owner,
                parent=None if node.parent is None else node.parent.block,
                type=node.type,
                content=node.content,
                plain_text=extract_plain_text(node.content),
                position=node.position,
            )
            for node in level
        ]
        Block.objects.bulk_create(rows)
        for node, row in zip(level, rows):
            node.block = row
        created.extend(rows)

    updated: list[Block] = []
    for node in nodes:
        block = node.block
        if node.fresh or block is None:
            continue
        parent_id = None if node.parent is None else node.parent.block.id
        if (
            block.type == node.type
            and (block.content or {}) == node.content
            and block.position == node.position
            and block.parent_id == parent_id
        ):
            continue
        block.type = node.type
        block.content = node.content
        block.plain_text = extract_plain_text(node.content)
        block.position = node.position
        block.parent_id = parent_id
        block.updated_at = now
        updated.append(block)
    if updated:
        Block.objects.bulk_update(
            updated,
            ["type", "content", "plain_text", "position", "parent", "updated_at"],
            batch_size=500,
        )
    if removed_ids:
        Block.objects.filter(id__in=removed_ids).update(deleted_at=now, updated_at=now)

    ids = [node.block.id for node in nodes]
    return SyncResult(
        seq=_publish(owner, actor, current_seq, created, updated, removed_ids, replaced=not kept),
        ids=ids,
        created=created,
        updated=updated,
        deleted_ids=removed_ids,
    )


def _publish(
    owner: Record | Page,
    actor,
    current_seq: int,
    created: list[Block],
    updated: list[Block],
    deleted_ids: list[int],
    *,
    replaced: bool,
) -> int:
    from workspace.utils import collab_block_body

    items: list[tuple[str, int | None, dict | None]] = [
        ("deleted", block_id, None) for block_id in deleted_ids
    ]
    items += [("created", block.id, collab_block_body(block)) for block in created]
    items += [("updated", block.id, collab_block_body(block)) for block in updated]
    if not items:
        return current_seq
    if len(items) > RELOAD_THRESHOLD or (replaced and deleted_ids):
        items = [("reload", None, None)]
    target = "record" if isinstance(owner, Record) else "page"
    return publish_collab_events(target, owner.pk, actor.id, items)


@transaction.atomic
def sync_page_blocks(user, page_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from workspace.access import require_content_write
    from workspace.tree import get_page
    from workspace.utils import serialize_block

    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지에만 블록을 저장할 수 있습니다.")
    require_content_write(user, page=page)
    lock_owner(page)
    edit = BodyEdit(page, user)
    result = sync_blocks(
        page, data.get("blocks") or [], user, edit=edit, base_seq=data.get("base_seq")
    )
    edit.finish(result.created + result.updated)
    if result.changed:
        publish_workspace_event(page.workspace_id, "page", "updated", page.id, user.id)
    return {
        "seq": result.seq,
        "ids": result.ids,
        "blocks": [serialize_block(block) for block in result.created + result.updated],
        "deleted_ids": result.deleted_ids,
    }
