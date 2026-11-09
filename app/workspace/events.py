from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

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
    publish_collab_events(target, target_id, actor_id, [(action, block_id, block)])


def publish_collab_events(
    target: str,
    target_id: int,
    actor_id: int | None,
    items: list[tuple[str, int | None, dict | None]],
) -> int:
    """여러 변경을 한 번의 락으로 이어 붙여 보냅니다. 마지막 `seq`를 돌려줍니다."""
    if not items:
        return 0
    seqs = _append_collab_events(target, target_id, actor_id, items)
    if not seqs:
        return 0
    payloads = [
        {
            "type": "collab",
            "action": action,
            "actor_id": actor_id,
            "block_id": block_id,
            "block": block,
            "seq": seq,
        }
        for seq, (action, block_id, block) in zip(seqs, items)
    ]

    def _send() -> None:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        for payload in payloads:
            async_to_sync(channel_layer.group_send)(
                f"collab_{target}_{target_id}",
                {"type": "collab.message", "sender": "", "payload": payload},
            )

    transaction.on_commit(_send)
    return seqs[-1]


def _append_collab_events(
    target: str,
    target_id: int,
    actor_id: int | None,
    items: list[tuple[str, int | None, dict | None]],
) -> list[int]:
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
            return []
        first = owner.collab_seq + 1
        owner.collab_seq += len(items)
        owner.save(update_fields=["collab_seq", "updated_at"])
        seqs = list(range(first, owner.collab_seq + 1))
        CollabEvent.objects.bulk_create(
            [
                CollabEvent(
                    seq=seq,
                    action=action,
                    actor_id=actor_id,
                    block_id=block_id,
                    block=block,
                    **owner_fields,
                )
                for seq, (action, block_id, block) in zip(seqs, items)
            ]
        )
        stale = list(stored.order_by("-seq").values_list("id", flat=True)[COLLAB_EVENT_LIMIT:])
        if stale:
            CollabEvent.objects.filter(id__in=stale).update(deleted_at=timezone.now())
        return seqs
