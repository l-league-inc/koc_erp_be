from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


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
