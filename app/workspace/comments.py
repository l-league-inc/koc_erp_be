"""블록 댓글입니다. 레코드 하단 댓글과는 별도입니다."""

from typing import Any

from django.utils import timezone
from ninja.errors import HttpError

from workspace.events import publish_workspace_event
from workspace.models import BlockComment, WorkspaceMember
from workspace.utils import get_block, get_membership


def _workspace_id(block) -> int:
    if block.record_id:
        return block.record.database.workspace_id
    return block.page.workspace_id


def _author_name(user) -> str:
    if user is None:
        return ""
    return user.name or ""


def serialize_block_comment(comment: BlockComment) -> dict[str, Any]:
    return {
        "id": comment.id,
        "block_id": comment.block_id,
        "parent_id": comment.parent_id,
        "author_id": comment.author_id,
        "author_name": _author_name(comment.author),
        "body": comment.body,
        "resolved_at": comment.resolved_at,
        "resolved_by_id": comment.resolved_by_id,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
    }


def get_block_comment(user, comment_id: int) -> BlockComment:
    comment = (
        BlockComment.objects.select_related(
            "block",
            "block__record",
            "block__record__database",
            "block__page",
            "author",
            "resolved_by",
        )
        .filter(id=comment_id)
        .first()
    )
    if comment is None:
        raise HttpError(404, "댓글을 찾을 수 없습니다.")
    get_block(user, comment.block_id)
    return comment


def list_block_comments(user, block_id: int) -> list[dict[str, Any]]:
    block = get_block(user, block_id)
    rows = BlockComment.objects.filter(block=block).select_related("author", "resolved_by").order_by("id")
    return [serialize_block_comment(row) for row in rows]


def create_block_comment(user, block_id: int, data: dict[str, Any]) -> dict[str, Any]:
    block = get_block(user, block_id)
    body = str(data.get("body") or "").strip()
    if not body:
        raise HttpError(400, "댓글 내용이 필요합니다.")
    parent = None
    if data.get("parent_id") is not None:
        parent = get_block_comment(user, int(data["parent_id"]))
        if parent.block_id != block.id:
            raise HttpError(400, "답글은 같은 블록의 댓글에만 달 수 있습니다.")
        if parent.parent_id is not None:
            raise HttpError(400, "답글에는 다시 답글을 달 수 없습니다.")
    comment = BlockComment.objects.create(block=block, author=user, parent=parent, body=body)
    publish_workspace_event(_workspace_id(block), "block_comment", "created", comment.id, user.id)
    return serialize_block_comment(comment)


def _require_comment_manager(user, comment: BlockComment) -> None:
    membership = get_membership(user, _workspace_id(comment.block))
    if comment.author_id != user.id and membership.role not in {
        WorkspaceMember.Role.OWNER,
        WorkspaceMember.Role.ADMIN,
    }:
        raise HttpError(403, "댓글을 바꿀 권한이 없습니다.")


def set_block_comment_resolved(user, comment_id: int, resolved: bool) -> dict[str, Any]:
    comment = get_block_comment(user, comment_id)
    if comment.parent_id is not None:
        raise HttpError(400, "답글은 해결 표시를 할 수 없습니다.")
    _require_comment_manager(user, comment)
    if resolved:
        comment.resolved_at = timezone.now()
        comment.resolved_by = user
    else:
        comment.resolved_at = None
        comment.resolved_by = None
    comment.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
    publish_workspace_event(
        _workspace_id(comment.block), "block_comment", "updated", comment.id, user.id
    )
    return serialize_block_comment(comment)


def delete_block_comment(user, comment_id: int) -> None:
    comment = get_block_comment(user, comment_id)
    _require_comment_manager(user, comment)
    for reply in BlockComment.objects.filter(parent=comment):
        reply.delete()
    workspace_id = _workspace_id(comment.block)
    deleted_id = comment.id
    comment.delete()
    publish_workspace_event(workspace_id, "block_comment", "deleted", deleted_id, user.id)
