from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from workspace.models import CollabEvent, Page, Record

COLLAB_EVENT_LIMIT = 100


def publish_workspace_event(
    workspace_id: int,
    entity: str,
    action: str,
    object_id: int,
    actor_id: int | None,
) -> None:
    """커밋된 뒤에만 워크스페이스 멤버에게 변경 사실을 알립니다."""

    def _send() -> None:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"workspace_{workspace_id}",
            {
                "type": "workspace.changed",
                "workspace_id": workspace_id,
                "entity": entity,
                "action": action,
                "id": object_id,
                "actor_id": actor_id,
            },
        )

    transaction.on_commit(_send)


def publish_collab_event(
    target: str,
    target_id: int,
    action: str,
    actor_id: int | None,
    block_id: int | None,
    block: dict | None,
) -> None:
    """문서방에 커밋된 블록 변경을 보냅니다. 글자 단위 병합은 하지 않습니다."""

    seq = _append_collab_event(target, target_id, action, actor_id, block_id, block)
    payload = {
        "type": "collab",
        "action": action,
        "actor_id": actor_id,
        "block_id": block_id,
        "block": block,
        "seq": seq,
    }

    def _send() -> None:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"collab_{target}_{target_id}",
            {"type": "collab.message", "sender": "", "payload": payload},
        )

    transaction.on_commit(_send)


def _append_collab_event(
    target: str,
    target_id: int,
    action: str,
    actor_id: int | None,
    block_id: int | None,
    block: dict | None,
) -> int:
    with transaction.atomic():
        if target == "record":
            owner = Record.objects.select_for_update().get(pk=target_id)
            owner_fields = {"record": owner}
            stored = CollabEvent.objects.filter(record=owner)
        elif target == "page":
            owner = Page.objects.select_for_update().get(pk=target_id)
            owner_fields = {"page": owner}
            stored = CollabEvent.objects.filter(page=owner)
        else:
            return 0
        owner.collab_seq += 1
        owner.save(update_fields=["collab_seq", "updated_at"])
        CollabEvent.objects.create(
            seq=owner.collab_seq,
            action=action,
            actor_id=actor_id,
            block_id=block_id,
            block=block,
            **owner_fields,
        )
        stale = list(stored.order_by("-seq")[COLLAB_EVENT_LIMIT:])
        for row in stale:
            row.delete()
        return owner.collab_seq
