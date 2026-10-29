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
from notification.fcm_utils import sync_send_multicast_push_notification
from asgiref.sync import sync_to_async


User = get_user_model()


class TestPushNotification(TestCase):
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

    async def test_push_notification(self):
        result = await sync_to_async(sync_send_multicast_push_notification)(
            tokens=["cuWziqyct0UJqVb0uvCd1N:APA91bEoyKX5owI80zaxT7NJrXe929WWcQ-fa-LsuFYZPd_WrmgST4dWIMeGyKk2o-m9iPo8ExCgybQhWYSRM6SPzOgB-xbx3ekYMH6sruYkjY12hHSjKxE"],
            title="테스트 푸시 알림",
            body="테스트 푸시 알림 본문",
        )
        # print("🐍 File: tests/test_push.py | Line: 101 | setUp ~ result",result)