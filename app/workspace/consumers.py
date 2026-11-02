import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from workspace.models import WorkspaceMember


class WorkspaceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        self.workspace_id = int(self.scope["url_route"]["kwargs"]["workspace_id"])
        self.group_name = None
        if not self.user or not await self._is_member():
            await self.close()
            return
        self.group_name = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def workspace_changed(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "workspace_changed",
                    "workspace_id": event["workspace_id"],
                    "entity": event["entity"],
                    "action": event["action"],
                    "id": event["id"],
                    "actor_id": event["actor_id"],
                }
            )
        )

    @database_sync_to_async
    def _is_member(self) -> bool:
        return WorkspaceMember.objects.filter(
            user_id=self.user.id,
            workspace_id=self.workspace_id,
        ).exists()
