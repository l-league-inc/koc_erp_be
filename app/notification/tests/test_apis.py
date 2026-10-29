from django.test import TestCase
from django.contrib.auth import get_user_model
from notification.api import router
from user.api import router as user_router
from ninja.testing import TestAsyncClient
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import timedelta
from notification.discord_utils import send_discord_message
from notification.models import Notification


User = get_user_model()


class TestNotification(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.auth_client = TestAsyncClient(user_router)
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="password1234!",
            phone_number="01011112222",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password1234!",
            phone_number="01099999999",
        )
        self.notification1 = Notification.objects.create(
            user=self.user, message="테스트 알림 1", is_read=False
        )
        self.notification2 = Notification.objects.create(
            user=self.user, message="테스트 알림 2", is_read=False
        )
        self.notification3 = Notification.objects.create(
            user=self.user, message="테스트 알림 3", is_read=True
        )

    async def authenticate(
        self, email="testuser@example.com", password="password1234!"
    ):
        data = {
            "email": email,
            "password": password,
        }
        response = await self.auth_client.post("/login", json=data)
        access = response.json().get("access")
        return {"Authorization": f"Bearer {access}"}

    async def test_get_notifications(self):
        """
        알림 목록 조회 테스트
        """
        headers = await self.authenticate()
        response = await self.client.get("", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        data = data.get("data")
        self.assertEqual(len(data), 3)

        # filtering by read status
        response = await self.client.get(
            "?is_read=false", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        data = data.get("data")
        self.assertEqual(len(data), 2)

    async def test_get_unread_notification_count(self):
        """
        읽지 않은 알림 개수 조회 테스트
        """
        headers = await self.authenticate()
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["unread_count"], 2)

    async def test_mark_all_notifications_as_read(self):
        """
        모든 알림 읽음 처리 테스트
        """
        headers = await self.authenticate()
        
        # 읽지 않은 알림 개수 확인
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.json()["unread_count"], 2)
        
        # 모든 알림 읽음 처리
        response = await self.client.get("/read-all", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "All notifications marked as read")
        
        # 읽지 않은 알림 개수 다시 확인
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.json()["unread_count"], 0)
        
        # 모든 알림이 읽음 상태인지 확인
        response = await self.client.get("", headers=headers)
        data = response.json().get("data")
        for notification in data:
            self.assertTrue(notification["is_read"])

    async def test_mark_notification_as_read(self):
        """
        특정 알림 읽음 처리 테스트
        """
        headers = await self.authenticate()
        
        # 특정 알림 읽음 처리
        notification_id = self.notification1.id
        response = await self.client.get(
            f"/read/{notification_id}", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Notification marked as read")
        
        # 읽음 처리된 알림 확인
        updated_notification = await Notification.objects.aget(id=notification_id)
        self.assertTrue(updated_notification.is_read)
        
        # 읽지 않은 알림 개수 확인 (2 -> 1)
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.json()["unread_count"], 1)

    async def test_mark_already_read_notification(self):
        """
        이미 읽은 알림을 다시 읽음 처리하는 테스트
        """
        headers = await self.authenticate()
        
        # 이미 읽은 알림 ID
        notification_id = self.notification3.id
        
        # 읽음 처리 (이미 읽은 상태)
        response = await self.client.get(
            f"/read/{notification_id}", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        
        # 읽지 않은 알림 개수는 변하지 않음
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.json()["unread_count"], 2)

    async def test_mark_nonexistent_notification_as_read(self):
        """
        존재하지 않는 알림 읽음 처리 테스트
        """
        headers = await self.authenticate()
        
        # 존재하지 않는 알림 ID
        nonexistent_id = 99999
        response = await self.client.get(
            f"/read/{nonexistent_id}", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        # 아무런 변화 없이 성공 응답

    async def test_notifications_filtered_by_read_status(self):
        """
        읽음 상태별 알림 필터링 테스트
        """
        headers = await self.authenticate()
        
        # 읽지 않은 알림만 조회
        response = await self.client.get("?is_read=false", headers=headers)
        data = response.json().get("data")
        self.assertEqual(len(data), 2)
        for notification in data:
            self.assertFalse(notification["is_read"])
        
        # 읽은 알림만 조회
        response = await self.client.get("?is_read=true", headers=headers)
        data = response.json().get("data")
        self.assertEqual(len(data), 1)
        for notification in data:
            self.assertTrue(notification["is_read"])

    async def test_notification_ordering(self):
        """
        알림 정렬 테스트 (최신순)
        """
        headers = await self.authenticate()
        response = await self.client.get("", headers=headers)
        data = response.json().get("data")
        
        # 최신 알림이 먼저 오는지 확인
        self.assertEqual(data[0]["id"], self.notification3.id)
        self.assertEqual(data[1]["id"], self.notification2.id)
        self.assertEqual(data[2]["id"], self.notification1.id)

    async def test_multiple_users_notifications_isolation(self):
        """
        여러 사용자의 알림 격리 테스트
        """
        # 다른 사용자 생성
        other_user = await sync_to_async(User.objects.create_user)(
            email="otheruser@example.com",
            password="password1234!",
            phone_number="01022223333",
        )
        
        # 다른 사용자의 알림 생성
        await Notification.objects.acreate(
            user=other_user, message="다른 사용자 알림", is_read=False
        )
        
        # 원래 사용자로 로그인하여 알림 조회
        headers = await self.authenticate()
        response = await self.client.get("", headers=headers)
        data = response.json().get("data")
        
        # 원래 사용자의 알림만 조회되는지 확인
        self.assertEqual(len(data), 3)
        for notification in data:
            self.assertEqual(notification["user"], self.user.id)

    async def test_read_all_when_no_unread_notifications(self):
        """
        읽지 않은 알림이 없을 때 모두 읽음 처리 테스트
        """
        headers = await self.authenticate()
        
        # 먼저 모든 알림 읽음 처리
        await self.client.get("/read-all", headers=headers)
        
        # 다시 모두 읽음 처리 시도
        response = await self.client.get("/read-all", headers=headers)
        self.assertEqual(response.status_code, 200)
        
        # 여전히 읽지 않은 알림 개수는 0
        response = await self.client.get("/unread-count", headers=headers)
        self.assertEqual(response.json()["unread_count"], 0)

        

    # async def test_discord_webhook(self):
    #     """
    #     Discord 웹훅 테스트
    #     """
    #     await send_discord_message("🔔 AI 이미지 생성 알림 테스트 메시지입니다!")
