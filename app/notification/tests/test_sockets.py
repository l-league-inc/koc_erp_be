# test_consumers.py
import json
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async
from django.test import TransactionTestCase
from user.models import User
from unittest.mock import patch, AsyncMock
from notification.consumers import NotificationConsumer
from notification.models import Notification
from unittest.mock import AsyncMock, MagicMock


class NotificationConsumerTest(TransactionTestCase):
    """
    NotificationConsumer 테스트 클래스
    """

    def setUp(self):
        """테스트 데이터 설정"""
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )

        # 테스트용 알림 생성
        self.notification1 = Notification.objects.create(
            user=self.user, message="테스트 알림 1", is_read=False
        )
        self.notification2 = Notification.objects.create(
            user=self.user, message="테스트 알림 2", is_read=False
        )

    async def test_websocket_connect_success(self):
        """웹소켓 정상 연결 테스트"""
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.user.id}/"
        )

        # scope에 user와 url_route 설정
        communicator.scope["user"] = self.user
        communicator.scope["url_route"] = {"kwargs": {"user_id": self.user.id}}

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # 연결 성공 메시지 확인
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "user_connected")
        self.assertEqual(response["user_id"], str(self.user.id))

        await communicator.disconnect()

    async def test_websocket_connect_unauthorized(self):
        """권한 없는 사용자 연결 거부 테스트"""
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.other_user.id}/"
        )

        # 다른 사용자 ID로 접근 시도
        communicator.scope["user"] = self.user
        communicator.scope["url_route"] = {"kwargs": {"user_id": self.other_user.id}}

        connected, subprotocol = await communicator.connect()
        self.assertFalse(connected)

    async def test_mark_notification_as_read(self):
        """알림 읽음 처리 테스트"""
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.user.id}/"
        )
        communicator.scope["user"] = self.user
        communicator.scope["url_route"] = {"kwargs": {"user_id": self.user.id}}

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # 연결 메시지 받기
        await communicator.receive_json_from()

        # 알림 읽음 처리 요청
        await communicator.send_json_to(
            {"type": "mark_as_read", "notification_id": self.notification1.id}
        )

        # 응답 확인
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "notification_marked_as_read")
        self.assertEqual(response["notification_id"], self.notification1.id)

        # 데이터베이스에서 실제로 읽음 처리되었는지 확인
        await database_sync_to_async(self.notification1.refresh_from_db)()
        self.assertTrue(self.notification1.is_read)

        await communicator.disconnect()

    async def test_mark_all_notifications_as_read(self):
        """모든 알림 읽음 처리 테스트"""
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.user.id}/"
        )
        communicator.scope["user"] = self.user
        communicator.scope["url_route"] = {"kwargs": {"user_id": self.user.id}}

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # 연결 메시지 받기
        await communicator.receive_json_from()

        # 모든 알림 읽음 처리 요청
        await communicator.send_json_to({"type": "mark_all_read"})

        # 응답 확인
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "all_notifications_marked_as_read")
        self.assertFalse(response["has_unread"])

        # 데이터베이스에서 모든 알림이 읽음 처리되었는지 확인
        unread_count = await database_sync_to_async(
            lambda: Notification.objects.filter(user=self.user, is_read=False).count()
        )()
        self.assertEqual(unread_count, 0)

        await communicator.disconnect()

    async def test_get_unread_notifications(self):
        """읽지 않은 알림 조회 테스트"""
        consumer = NotificationConsumer()
        consumer.user = self.user

        unread_notifications = await consumer.get_unread_notifications()

        # 읽지 않은 알림이 2개인지 확인
        self.assertEqual(len(unread_notifications), 2)

        # 알림 내용 확인
        messages = [notif["message"] for notif in unread_notifications]
        self.assertIn("테스트 알림 1", messages)
        self.assertIn("테스트 알림 2", messages)

    async def test_check_has_unread(self):
        """읽지 않은 알림 존재 여부 확인 테스트"""
        consumer = NotificationConsumer()
        consumer.user = self.user

        # 읽지 않은 알림이 있는 경우
        has_unread = await consumer.check_has_unread()
        self.assertTrue(has_unread)

        # 모든 알림을 읽음 처리
        await database_sync_to_async(
            lambda: Notification.objects.filter(user=self.user).update(is_read=True)
        )()

        # 읽지 않은 알림이 없는 경우
        has_unread = await consumer.check_has_unread()
        self.assertFalse(has_unread)

    async def test_invalid_json_message(self):
        """잘못된 JSON 메시지 처리 테스트"""
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.user.id}/"
        )
        communicator.scope["user"] = self.user
        communicator.scope["url_route"] = {"kwargs": {"user_id": self.user.id}}

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # 연결 메시지 받기
        await communicator.receive_json_from()

        # 잘못된 JSON 전송
        await communicator.send_to(text_data="invalid json")

        # 에러 응답 확인
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "error")

        await communicator.disconnect()

    async def test_mark_nonexistent_notification(self):
        """존재하지 않는 알림 읽음 처리 테스트"""
        consumer = NotificationConsumer()
        consumer.user = self.user

        # 존재하지 않는 알림 ID로 읽음 처리 시도
        result = await consumer.mark_notification_as_read(99999)
        self.assertFalse(result)


class NotificationIntegrationTest(TransactionTestCase):
    """통합 테스트"""

    def setUp(self):
        self.sender = User.objects.create_user(
            username="sender", email="sender@example.com", password="testpass123"
        )
        self.receiver = User.objects.create_user(
            username="receiver", email="receiver@example.com", password="testpass123"
        )

    async def test_end_to_end_notification_flow(self):
        """전체 알림 플로우 테스트"""
        # 수신자 웹소켓 연결
        receiver_communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), f"/ws/notifications/{self.receiver.id}/"
        )
        receiver_communicator.scope["user"] = self.receiver
        receiver_communicator.scope["url_route"] = {
            "kwargs": {"user_id": self.receiver.id}
        }

        connected, _ = await receiver_communicator.connect()
        self.assertTrue(connected)

        # 연결 메시지 받기
        await receiver_communicator.receive_json_from()

        # 새 알림 생성
        notification = await database_sync_to_async(Notification.objects.create)(
            user=self.receiver,
            message=f"{self.sender.username}님이 초대장을 보냈습니다",
            is_read=False,
        )

        # 알림 읽음 처리
        await receiver_communicator.send_json_to(
            {"type": "mark_as_read", "notification_id": notification.id}
        )

        # 읽음 처리 응답 확인
        response = await receiver_communicator.receive_json_from()
        self.assertEqual(response["type"], "notification_marked_as_read")

        await receiver_communicator.disconnect()


class NotificationPerformanceTest(TransactionTestCase):
    """성능 테스트"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="perf_user", email="perf@example.com", password="testpass123"
        )

        # 대량의 알림 생성
        notifications = []
        for i in range(100):
            notifications.append(
                Notification(
                    user=self.user, message=f"성능 테스트 알림 {i}", is_read=False
                )
            )
        Notification.objects.bulk_create(notifications)

    async def test_large_notification_list_performance(self):
        """대량 알림 조회 성능 테스트"""
        consumer = NotificationConsumer()
        consumer.user = self.user

        import time

        start_time = time.time()

        notifications = await consumer.get_unread_notifications()

        end_time = time.time()
        execution_time = end_time - start_time

        # 100개 알림 조회가 1초 이내에 완료되는지 확인
        self.assertLess(execution_time, 1.0)
        self.assertEqual(len(notifications), 100)
