"""문서를 고치기 직전의 본문을 남기고 되돌립니다."""

from typing import Any

from django.db import transaction
from ninja.errors import HttpError

from workspace.access import require_content_write
from workspace.mentions import notify_new_user_mentions
from workspace.models import Block, DocumentRevision, Page, Property, Record, RecordActivity

REVISION_LIMIT = 50


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


def after_record_edit(record: Record, actor, before: dict[str, Any]) -> None:
    after = record_body(record)
    if before == after:
        return
    DocumentRevision.objects.create(record=record, actor=actor, body=before)
    _prune(DocumentRevision.objects.filter(record=record))
    notify_new_user_mentions(
        before,
        list(record.blocks.order_by("position", "id")),
        actor,
        workspace_id=record.database.workspace_id,
        target="record",
        target_id=record.id,
        label=record.title,
    )


def after_page_edit(page: Page, actor, before: dict[str, Any]) -> None:
    after = page_body(page)
    if before == after:
        return
    DocumentRevision.objects.create(page=page, actor=actor, body=before)
    _prune(DocumentRevision.objects.filter(page=page))
    notify_new_user_mentions(
        before,
        list(page.blocks.order_by("position", "id")),
        actor,
        workspace_id=page.workspace_id,
        target="page",
        target_id=page.id,
        label=page.name,
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
    from workspace.utils import create_block_tree

    for block in list(page.blocks.all()):
        block.delete()
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
    before = record_body(record)
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
    after_record_edit(record, user, before)
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
    before = page_body(page)
    body = revision.body or {}
    _replace_page_blocks(page, body.get("blocks") or [], user.id)
    after_page_edit(page, user, before)
    publish_workspace_event(page.workspace_id, "page", "updated", page.id, user.id)
    return serialize_page(page, include_blocks=True)
