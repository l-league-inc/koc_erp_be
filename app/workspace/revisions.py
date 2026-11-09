"""문서를 고치기 직전의 본문을 남기고 되돌립니다."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from workspace.access import require_content_write
from workspace.mentions import block_user_ids, known_user_ids, notify_new_user_mentions
from workspace.models import Block, DocumentRevision, Page, Property, Record, RecordActivity

REVISION_LIMIT = 50
REVISION_INTERVAL = timedelta(minutes=5)


def block_tree(blocks: list[Block]) -> list[dict[str, Any]]:
    grouped: dict[int | None, list[Block]] = {}
    for block in blocks:
        grouped.setdefault(block.parent_id, []).append(block)

    def build(parent_id: int | None) -> list[dict[str, Any]]:
        nodes = []
        children = sorted(grouped.get(parent_id, []), key=lambda item: (item.position, item.id))
        for block in children:
            nodes.append(
                {
                    "type": block.type,
                    "content": block.content or {},
                    "position": block.position,
                    "children": build(block.id),
                }
            )
        return nodes

    return build(None)


def record_body(record: Record) -> dict[str, Any]:
    from workspace.utils import _raw_values

    return {
        "title": record.title,
        "icon": record.icon,
        "values": _raw_values(record),
        "blocks": block_tree(list(record.blocks.order_by("position", "id"))),
    }


def page_body(page: Page) -> dict[str, Any]:
    return {"blocks": block_tree(list(page.blocks.order_by("position", "id")))}


def _prune(qs) -> None:
    stale = list(qs.order_by("-id")[REVISION_LIMIT:])
    for row in stale:
        row.delete()


class BodyEdit:
    """본문 한 번 고치는 동안의 개정과 멘션 알림을 맡습니다.

    같은 사용자가 `REVISION_INTERVAL` 안에 다시 고치면 새 개정을 만들지 않습니다.
    그 경우 첫 수정 직전 본문이 이미 개정에 있으므로 전체 본문을 읽지 않습니다.
    멘션은 바뀐 블록에 사용자 멘션이 있을 때만 기존 멘션을 조회합니다.
    """

    def __init__(self, owner: Record | Page, actor, *, force: bool = False) -> None:
        self.owner = owner
        self.actor = actor
        self.known: set[int] | None = None
        self.before = self._body() if force or self._due() else None

    def _body(self) -> dict[str, Any]:
        return record_body(self.owner) if isinstance(self.owner, Record) else page_body(self.owner)

    def _revisions(self):
        field = "record" if isinstance(self.owner, Record) else "page"
        return DocumentRevision.objects.filter(**{field: self.owner})

    def _due(self) -> bool:
        last = self._revisions().order_by("-id").values_list("actor_id", "created_at").first()
        if last is None:
            return True
        actor_id, created_at = last
        return actor_id != self.actor.id or timezone.now() - created_at >= REVISION_INTERVAL

    def track_mentions(self) -> None:
        if self.known is None:
            self.known = known_user_ids(self.owner.blocks)

    def watch(self, content: Any) -> None:
        """저장하기 전에 새 내용을 넘깁니다. 사용자 멘션이 있을 때만 기존 멘션을 읽습니다."""
        if content and block_user_ids(content):
            self.track_mentions()

    def finish(self, changed: list[Block] | None = None) -> None:
        if self.before is not None and self._body() != self.before:
            field = "record" if isinstance(self.owner, Record) else "page"
            DocumentRevision.objects.create(
                **{field: self.owner}, actor=self.actor, body=self.before
            )
            _prune(self._revisions())
        if self.known is None or not changed:
            return
        if isinstance(self.owner, Record):
            workspace_id, target, label = self.owner.database.workspace_id, "record", self.owner.title
        else:
            workspace_id, target, label = self.owner.workspace_id, "page", self.owner.name
        notify_new_user_mentions(
            self.known,
            changed,
            self.actor,
            workspace_id=workspace_id,
            target=target,
            target_id=self.owner.id,
            label=label,
        )


def _actor_name(user) -> str:
    if user is None:
        return ""
    return user.name or ""


def _summary(revision: DocumentRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "actor_id": revision.actor_id,
        "actor_name": _actor_name(revision.actor),
        "created_at": revision.created_at,
    }


def list_record_revisions(user, record_id: int) -> list[dict[str, Any]]:
    from workspace.utils import get_record

    record = get_record(user, record_id)
    rows = (
        DocumentRevision.objects.filter(record=record)
        .select_related("actor")
        .order_by("-id")[:REVISION_LIMIT]
    )
    return [_summary(row) for row in rows]


def list_page_revisions(user, page_id: int) -> list[dict[str, Any]]:
    from workspace.tree import get_page

    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지에만 개정이 있습니다.")
    rows = (
        DocumentRevision.objects.filter(page=page)
        .select_related("actor")
        .order_by("-id")[:REVISION_LIMIT]
    )
    return [_summary(row) for row in rows]


def _record_revision(user, record_id: int, revision_id: int) -> tuple[Record, DocumentRevision]:
    from workspace.utils import get_record

    record = get_record(user, record_id)
    revision = (
        DocumentRevision.objects.select_related("actor")
        .filter(id=revision_id, record=record)
        .first()
    )
    if revision is None:
        raise HttpError(404, "개정을 찾을 수 없습니다.")
    return record, revision


def _page_revision(user, page_id: int, revision_id: int) -> tuple[Page, DocumentRevision]:
    from workspace.tree import get_page

    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지에만 개정이 있습니다.")
    revision = (
        DocumentRevision.objects.select_related("actor")
        .filter(id=revision_id, page=page)
        .first()
    )
    if revision is None:
        raise HttpError(404, "개정을 찾을 수 없습니다.")
    return page, revision


def get_record_revision(user, record_id: int, revision_id: int) -> dict[str, Any]:
    _record, revision = _record_revision(user, record_id, revision_id)
    payload = _summary(revision)
    payload["body"] = revision.body or {}
    return payload


def get_page_revision(user, page_id: int, revision_id: int) -> dict[str, Any]:
    _page, revision = _page_revision(user, page_id, revision_id)
    payload = _summary(revision)
    payload["body"] = revision.body or {}
    return payload


def _replace_page_blocks(page: Page, blocks: list[dict], actor_id: int | None) -> None:
    from workspace.events import publish_collab_event
    from workspace.utils import create_block_tree, soft_delete_blocks

    soft_delete_blocks(list(page.blocks.values_list("id", flat=True)))
    create_block_tree(None, blocks, None, page)
    publish_collab_event("page", page.id, "reload", actor_id, None, None)


@transaction.atomic
def restore_record_revision(user, record_id: int, revision_id: int, source: str) -> dict[str, Any]:
    from workspace.events import publish_workspace_event
    from workspace.utils import (
        _snapshot,
        apply_values,
        log_activity,
        replace_blocks,
        serialize_record,
    )

    record, revision = _record_revision(user, record_id, revision_id)
    require_content_write(user, database=record.database)
    activity_before = _snapshot(record)
    edit = BodyEdit(record, user, force=True)
    edit.track_mentions()
    body = revision.body or {}
    title = str(body.get("title") or "").strip()
    if not title:
        raise HttpError(400, "제목은 비울 수 없습니다.")
    record.title = title
    record.icon = str(body.get("icon") or "")
    values = dict(body.get("values") or {})
    for prop in record.database.properties.all():
        if prop.slug not in values and prop.type != Property.Type.TITLE:
            values[prop.slug] = None
    apply_values(record, values)
    replace_blocks(record, body.get("blocks") or [], user.id)
    record.last_edited_by = user
    record.save(update_fields=["title", "icon", "last_edited_by", "updated_at"])
    edit.finish(list(record.blocks.order_by("position", "id")))
    log_activity(
        record,
        user,
        RecordActivity.Action.UPDATED,
        activity_before,
        _snapshot(record),
        source,
    )
    publish_workspace_event(record.database.workspace_id, "record", "updated", record.id, user.id)
    return serialize_record(record, include_blocks=True)


@transaction.atomic
def restore_page_revision(user, page_id: int, revision_id: int) -> dict[str, Any]:
    from workspace.events import publish_workspace_event
    from workspace.tree import serialize_page

    page, revision = _page_revision(user, page_id, revision_id)
    require_content_write(user, page=page)
    edit = BodyEdit(page, user, force=True)
    edit.track_mentions()
    body = revision.body or {}
    _replace_page_blocks(page, body.get("blocks") or [], user.id)
    edit.finish(list(page.blocks.order_by("position", "id")))
    publish_workspace_event(page.workspace_id, "page", "updated", page.id, user.id)
    return serialize_page(page, include_blocks=True)
