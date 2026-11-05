"""본문에 새로 등장한 사용자 멘션을 알림으로 보냅니다."""

from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db import transaction

from notification.utils import make_notification_sync
from workspace.models import Block

User = get_user_model()


def mention_user_ids(body: dict[str, Any]) -> set[int]:
    found: set[int] = set()

    def walk(blocks: list) -> None:
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            content = block.get("content") if isinstance(block.get("content"), dict) else {}
            for item in content.get("rich_text") or []:
                if not isinstance(item, dict):
                    continue
                mention = item.get("mention")
                if not isinstance(mention, dict) or mention.get("type") != "user":
                    continue
                user_id = mention.get("user_id")
                if isinstance(user_id, bool) or not isinstance(user_id, int):
                    continue
                found.add(user_id)
            walk(block.get("children") or [])

    walk(body.get("blocks") or [])
    return found


def _block_user_ids(content: dict) -> set[int]:
    return mention_user_ids({"blocks": [{"content": content or {}}]})


def notify_new_user_mentions(
    before: dict[str, Any],
    blocks: list[Block],
    actor,
    *,
    workspace_id: int,
    target: str,
    target_id: int,
    label: str,
) -> None:
    fresh = mention_user_ids(before)
    pending: list[tuple[int, int]] = []
    for block in blocks:
        for user_id in _block_user_ids(block.content or {}):
            if user_id in fresh or user_id == actor.id:
                continue
            pending.append((user_id, block.id))
            fresh.add(user_id)
    if not pending:
        return
    name = (actor.name or "").strip() or "멤버"
    title = (label or "").strip() or "문서"
    message = f"{name}님이 '{title}'에서 멘션했습니다."[:200]

    def _send() -> None:
        users = {
            user.id: user
            for user in User.objects.filter(id__in=[user_id for user_id, _block_id in pending])
        }
        channel_layer = get_channel_layer()
        for user_id, block_id in pending:
            user = users.get(user_id)
            if user is None:
                continue
            metadata = {
                "kind": "mention",
                "workspace_id": workspace_id,
                "target": target,
                "target_id": target_id,
                "block_id": block_id,
            }
            make_notification_sync(user, message, metadata)
            if channel_layer is None:
                continue
            async_to_sync(channel_layer.group_send)(
                f"notification_{user_id}",
                {
                    "type": "new_notification",
                    "notification": {"message": message, "metadata": metadata},
                    "has_unread": True,
                },
            )

    transaction.on_commit(_send)
