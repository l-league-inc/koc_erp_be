from django.test import TestCase
from django.contrib.auth import get_user_model
from ninja.testing import TestAsyncClient
from notice.api import router
from user.api import router as user_router
from notice.models import Notice
from notification.models import Notification

User = get_user_model()


class TestNotice(TestCase):
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
        self.notice = Notice.objects.create(
            user=self.user,
            type="notice",
            title="테스트 공지사항",
            content="테스트 공지사항 내용",
        )
        self.notice2 = Notice.objects.create(
            user=self.user,
            type="event",
            title="테스트 이벤트",
            content="테스트 이벤트 내용",
            render=Notice.RenderChoices.url,
        )
        self.notice3 = Notice.objects.create(
            user=self.user,
            type="urgent",
            title="긴급 공지",
            content="긴급 공지 내용",
            hidden=True,
        )
        self.active_user = User.objects.create_user(
            email="activeuser@example.com",
            password="password1234!",
            phone_number="01033334444",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.toss_active_user = User.objects.create_user(
            email="tossactive@example.com",
            password="password1234!",
            phone_number="01055556666",
            login_method=User.LoginMethodChoices.TOSS,
            status=User.UserStatusChoice.ACTIVE,
        )
        self.inactive_user = User.objects.create_user(
            email="inactive@example.com",
            password="password1234!",
            phone_number="01077778888",
            status=User.UserStatusChoice.INACTIVE,
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

    async def test_admin_notice_list(self):
        """관리자 공지사항 목록 조회 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        response = await self.client.get("/admin", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        data = data.get("data")
        self.assertEqual(len(data), 3)

        # type filter
        response = await self.client.get("/admin?type=notice", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        data = data.get("data")
        self.assertEqual(len(data), 1)

        # render filter
        response = await self.client.get("/admin?render=url", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        data = data.get("data")
        self.assertEqual(len(data), 1)

    async def test_admin_notice_create(self):
        """관리자 공지사항 생성 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        payload = {
            "title": "새로운 공지사항",
            "content": "새로운 공지사항 내용",
            "type": "notice",
        }
        response = await self.client.post("/admin", json=payload, headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(data.get("title"), "새로운 공지사항")

    async def test_admin_notice_create_makes_notifications(self):
        """공개 공지 생성 시 활성/비토스 유저에게만 알림 생성 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        payload = {
            "title": "알림 생성 공지",
            "content": "알림 생성 테스트",
            "type": "notice",
        }

        response = await self.client.post("/admin", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201)
        created_notice_id = response.json().get("id")

        notice = await Notice.objects.aget(id=created_notice_id)
        self.assertTrue(notice.is_notification_sent)

        notifications = [
            notification
            async for notification in Notification.objects.filter(
                metadata__notice_id=created_notice_id
            ).order_by("id")
        ]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].user_id, self.active_user.id)
        self.assertEqual(notifications[0].message, "[공지] 알림 생성 공지")

    async def test_admin_notice_create_hidden_does_not_make_notifications(self):
        """비공개 공지 생성 시 알림 미생성 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        payload = {
            "title": "숨김 공지",
            "content": "비공개 공지",
            "type": "notice",
            "hidden": True,
        }

        response = await self.client.post("/admin", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201)
        created_notice_id = response.json().get("id")

        notice = await Notice.objects.aget(id=created_notice_id)
        self.assertFalse(notice.is_notification_sent)

        notification_count = await Notification.objects.filter(
            metadata__notice_id=created_notice_id
        ).acount()
        self.assertEqual(notification_count, 0)

    async def test_admin_notice_detail(self):
        """관리자 공지사항 상세 조회 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        response = await self.client.get(f"/admin/{self.notice.id}", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("title"), "테스트 공지사항")

    async def test_admin_notice_update(self):
        """관리자 공지사항 수정 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        payload = {
            "title": "수정된 공지사항",
            "content": "수정된 공지사항 내용",
            "hidden": True,
        }
        response = await self.client.patch(
            f"/admin/{self.notice.id}", json=payload, headers=headers
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("title"), "수정된 공지사항")
        self.assertTrue(data.get("hidden"))

    async def test_admin_notice_update_hidden_to_public_makes_notifications_once(self):
        """비공개 공지 공개 전환 시 1회만 알림 생성 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        notice = await Notice.objects.acreate(
            user=self.admin,
            type="urgent",
            title="숨김 공지",
            content="초기 비공개",
            hidden=True,
        )

        response = await self.client.patch(
            f"/admin/{notice.id}", json={"hidden": False}, headers=headers
        )
        self.assertEqual(response.status_code, 200)

        notification_count = await Notification.objects.filter(
            metadata__notice_id=notice.id
        ).acount()
        self.assertEqual(notification_count, 1)

        updated_notice = await Notice.objects.aget(id=notice.id)
        self.assertTrue(updated_notice.is_notification_sent)

        response = await self.client.patch(
            f"/admin/{notice.id}",
            json={"title": "공개 후 수정"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)

        notification_count = await Notification.objects.filter(
            metadata__notice_id=notice.id
        ).acount()
        self.assertEqual(notification_count, 1)

    async def test_admin_notice_delete(self):
        """관리자 공지사항 삭제 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        response = await self.client.delete(f"/admin/{self.notice.id}", headers=headers)
        self.assertEqual(response.status_code, 204)

    async def test_user_notice_list(self):
        """사용자 공지사항 목록 조회 테스트"""
        headers = await self.authenticate()
        response = await self.client.get("/", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        data = data.get("data")
        self.assertEqual(len(data), 2)

    async def test_user_notice_detail(self):
        """사용자 공지사항 상세 조회 테스트"""
        headers = await self.authenticate()
        response = await self.client.get(f"/{self.notice.id}", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("title"), "테스트 공지사항")
        self.assertEqual(data.get("content"), "테스트 공지사항 내용")
