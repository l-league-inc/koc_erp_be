"""`new_notification` WebSocket push 테스트.

`group_send`의 `type`과 Consumer 핸들러 메서드명이 어긋나면
`ValueError: No handler for message type ...`로 소켓이 끊긴다.
그 회귀를 막기 위한 테스트다.
"""

import asyncio

from asgiref.sync import sync_to_async
from channels.consumer import get_handler_name
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from notification.consumers import NotificationConsumer
from user.models import User

# 백엔드가 notification_{user_id} 그룹으로 보내는 모든 이벤트 타입
SERVER_EVENT_TYPES = [
    "new_notification",
    "badge_earned",
    "user_notification_connected",
    "user_notification_disconnected",
    "notification_marked_as_read",
    "all_notifications_marked_as_read",
    "error_occurred",
]


class NewNotificationWebSocketTest(TransactionTestCase):
    """초대 알림 WS push 및 이벤트 타입 ↔ 핸들러 정합성 테스트."""

    def setUp(self) -> None:
        self.inviter = User.objects.create_user(
            email="inviter@example.com", password="testpass123"
        )
        self.invited_user = User.objects.create_user(
            email="invited@example.com", password="testpass123"
        )

    async def _connect(self, user) -> WebsocketCommunicator:
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notification/{user.id}/"
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {"kwargs": {"user_id": user.id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        connected_msg = await communicator.receive_json_from()
        self.assertEqual(connected_msg["type"], "user_connected")
        return communicator

    def test_all_server_event_types_have_handler(self) -> None:
        """group_send로 보내는 모든 타입에 대응하는 핸들러가 있어야 한다."""
        for event_type in SERVER_EVENT_TYPES:
            with self.subTest(event_type=event_type):
                handler_name = get_handler_name({"type": event_type})
                self.assertTrue(
                    hasattr(NotificationConsumer, handler_name),
                    f"'{event_type}' 이벤트를 받을 핸들러 "
                    f"NotificationConsumer.{handler_name}()가 없습니다.",
                )

    async def test_group_send_new_notification_is_delivered(self) -> None:
        """message 키로 보낸 payload가 클라이언트까지 전달된다."""
        communicator = await self._connect(self.invited_user)
        channel_layer = get_channel_layer()

        await channel_layer.group_send(
            f"notification_{self.invited_user.id}",
            {
                "type": "new_notification",
                "message": "초대장이 도착했습니다.",
                "has_unread": True,
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "new_notification")
        self.assertEqual(response["notification"], "초대장이 도착했습니다.")
        self.assertTrue(response["has_unread"])

        await communicator.disconnect()

    async def test_group_send_accepts_notification_key(self) -> None:
        """notification 키(object payload)로 보내도 그대로 전달된다."""
        communicator = await self._connect(self.invited_user)
        channel_layer = get_channel_layer()
        payload = {"id": 1, "message": "댓글이 달렸어요."}

        await channel_layer.group_send(
            f"notification_{self.invited_user.id}",
            {
                "type": "new_notification",
                "notification": payload,
                "has_unread": False,
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["notification"], payload)
        self.assertFalse(response["has_unread"])

        await communicator.disconnect()

    async def test_handler_tolerates_missing_keys(self) -> None:
        """payload 키가 없어도 소켓이 끊기지 않는다."""
        communicator = await self._connect(self.invited_user)
        channel_layer = get_channel_layer()

        await channel_layer.group_send(
            f"notification_{self.invited_user.id}", {"type": "new_notification"}
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "new_notification")
        self.assertIsNone(response["notification"])
        self.assertTrue(response["has_unread"])

        await communicator.disconnect()
