import json
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder
from ninja.errors import HttpError

from workspace.collab import (
    apply_collab_op,
    clean_awareness,
    document_blocks,
    drop_presence,
    presence_payload,
    touch_presence,
)
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


class CollabConsumer(AsyncWebsocketConsumer):
    """한 레코드나 문서 페이지의 블록 편집과 커서를 전파합니다."""

    async def connect(self):
        self.user = self.scope.get("user")
        self.workspace_id = int(self.scope["url_route"]["kwargs"]["workspace_id"])
        self.target = str(self.scope["url_route"]["kwargs"]["target"])
        self.target_id = int(self.scope["url_route"]["kwargs"]["target_id"])
        self.group_name = None
        self.presence_id = uuid.uuid4().hex[:12]
        if self.target not in {"record", "page"} or not self.user:
            await self.close()
            return
        if not await self._can_join():
            await self.close()
            return
        self.group_name = f"collab_{self.target}_{self.target_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        people = await self._join_presence()
        blocks = await self._blocks()
        await self._send({"type": "sync", "target": self.target, "target_id": self.target_id, "blocks": blocks})
        await self._send(presence_payload(people))
        await self._broadcast(presence_payload(people))

    async def disconnect(self, close_code):
        if not self.group_name:
            return
        people = await self._leave_presence()
        await self._broadcast(presence_payload(people))
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            await self._send({"type": "error", "detail": "텍스트 메시지만 받습니다."})
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send({"type": "error", "detail": "JSON 형식이 올바르지 않습니다."})
            return
        if not isinstance(data, dict):
            await self._send({"type": "error", "detail": "메시지는 객체여야 합니다."})
            return
        kind = data.get("type")
        try:
            if kind == "ping":
                await self._join_presence(keep_cursor=True)
                await self._send({"type": "pong"})
                return
            if kind == "awareness":
                cursor, selection = clean_awareness(data)
                people = await self._join_presence(cursor=cursor, selection=selection)
                user = next(item for item in people.values() if item["presence_id"] == self.presence_id)
                await self._broadcast(
                    {
                        "type": "awareness",
                        "presence_id": self.presence_id,
                        "user_id": self.user.id,
                        "name": user.get("name") or "",
                        "cursor": cursor,
                        "selection": selection,
                    }
                )
                return
            if kind == "op":
                await self._op(data)
                await self._join_presence(keep_cursor=True)
                return
        except HttpError as exc:
            await self._send({"type": "error", "detail": exc.message})
            return
        await self._send({"type": "error", "detail": "지원하지 않는 메시지입니다."})

    async def collab_message(self, event):
        if event.get("sender") and event["sender"] == self.channel_name:
            return
        await self._send(event["payload"])

    async def _broadcast(self, payload: dict) -> None:
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "collab.message", "sender": self.channel_name, "payload": payload},
        )

    async def _send(self, payload: dict) -> None:
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    @database_sync_to_async
    def _can_join(self) -> bool:
        try:
            return document_blocks(self.user, self.workspace_id, self.target, self.target_id) is not None
        except HttpError:
            return False

    @database_sync_to_async
    def _blocks(self):
        blocks = document_blocks(self.user, self.workspace_id, self.target, self.target_id)
        return blocks or []

    @database_sync_to_async
    def _join_presence(self, cursor=None, selection=None, keep_cursor: bool = False):
        return touch_presence(
            self.target,
            self.target_id,
            channel_name=self.channel_name,
            presence_id=self.presence_id,
            user_id=self.user.id,
            name=self.user.name or "",
            cursor=cursor,
            selection=selection,
            keep_cursor=keep_cursor,
        )

    @database_sync_to_async
    def _leave_presence(self):
        return drop_presence(self.target, self.target_id, self.channel_name)

    @database_sync_to_async
    def _op(self, data: dict) -> None:
        apply_collab_op(self.user, self.target, self.target_id, data)
