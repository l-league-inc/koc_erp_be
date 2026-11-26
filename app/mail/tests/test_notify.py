from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from ninja.testing import TestAsyncClient

from mail.api import router
from mail.crypto import encrypt_secret
from mail.importance import classify_importance
from mail.models import UserMailAccount
from mail.watch import poll_account
from notification.models import Notification
from user.utils import get_access_token

User = get_user_model()


class ImportanceTests(SimpleTestCase):
    def test_deadline_and_outage_are_urgent(self):
        self.assertEqual(
            classify_importance(subject="오늘 마감 견적", sender="a@client.kr", snippet=""),
            "urgent",
        )
        self.assertEqual(
            classify_importance(subject="서버 다운", sender="ops@koc.kr", snippet="확인 부탁"),
            "urgent",
        )

    def test_newsletter_is_low_and_reply_is_normal(self):
        self.assertEqual(
            classify_importance(
                subject="11월 뉴스레터",
                sender="noreply@news.example",
                snippet="수신거부",
            ),
            "low",
        )
        self.assertEqual(
            classify_importance(subject="견적 회신", sender="a@client.kr", snippet="검토했습니다"),
            "normal",
        )

    def test_urgent_phrase_wins_over_newsletter_sender(self):
        self.assertEqual(
            classify_importance(
                subject="미수금 독촉",
                sender="noreply@billing.example",
                snippet="",
            ),
            "urgent",
        )


class MailWatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="mail-watch@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.account = UserMailAccount.objects.create(
            user=self.user,
            username="worker",
            password_encrypted=encrypt_secret("secret"),
            is_verified=True,
        )

    def test_first_poll_marks_the_inbox_and_the_next_poll_notifies(self):
        baseline = {"uidvalidity": 9, "highest": 10, "messages": []}
        arrived = {
            "uidvalidity": 9,
            "highest": 11,
            "messages": [
                {
                    "uid": "11",
                    "folder": "INBOX",
                    "subject": "오늘 마감 견적",
                    "sender": "client@example.com",
                    "snippet": "금일 마감입니다",
                    "flags": ["unseen"],
                    "date": None,
                }
            ],
        }
        with patch("mail.watch.daum.inbox_since", return_value=baseline) as fetched:
            self.assertEqual(poll_account(self.account.id), 0)
        fetched.assert_called_once()
        self.account.refresh_from_db()
        self.assertEqual(self.account.inbox_last_uid, 10)
        self.assertEqual(self.account.inbox_uidvalidity, 9)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)

        sent: list[tuple] = []

        async def group_send(group, message):
            sent.append((group, message))

        with (
            patch("mail.watch.daum.inbox_since", return_value=arrived),
            patch(
                "mail.watch.get_channel_layer",
                return_value=SimpleNamespace(group_send=group_send),
            ),
        ):
            self.assertEqual(poll_account(self.account.id), 1)
        note = Notification.objects.get(user=self.user)
        self.assertIn("[긴급]", note.message)
        self.assertEqual(note.metadata["kind"], "mail")
        self.assertEqual(note.metadata["importance"], "urgent")
        self.assertEqual(note.metadata["uid"], "11")
        self.assertEqual(sent[0][0], f"notification_{self.user.id}")
        event = sent[0][1]
        self.assertEqual(event["type"], "new_notification")
        self.assertTrue(event["has_unread"])
        self.assertEqual(event["notification"]["id"], note.id)
        self.assertEqual(event["notification"]["metadata"]["uid"], "11")
        self.assertFalse(event["notification"]["is_read"])
        self.account.refresh_from_db()
        self.assertEqual(self.account.inbox_last_uid, 11)

    def test_filtered_importance_advances_without_a_notification(self):
        self.account.inbox_uidvalidity = 3
        self.account.inbox_last_uid = 4
        self.account.notify_importances = ["urgent", "normal"]
        self.account.save(
            update_fields=["inbox_uidvalidity", "inbox_last_uid", "notify_importances", "updated_at"]
        )
        arrived = {
            "uidvalidity": 3,
            "highest": 5,
            "messages": [
                {
                    "uid": "5",
                    "subject": "11월 뉴스레터",
                    "sender": "noreply@news.example",
                    "snippet": "수신거부",
                }
            ],
        }
        with patch("mail.watch.daum.inbox_since", return_value=arrived):
            self.assertEqual(poll_account(self.account.id), 0)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.inbox_last_uid, 5)


class MailNotifyApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="mail-notify@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )

    def headers(self):
        token, _expires = get_access_token(
            {"user_id": self.user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_notify_range_rejects_empty_and_saves_urgent_and_normal(self):
        with patch("mail.service.daum.test_connection"):
            saved = await self.client.put(
                "/account",
                json={"username": "daumid", "app_password": "secret"},
                headers=self.headers(),
            )
        self.assertEqual(saved.json()["notify_importances"], ["urgent", "normal", "low"])
        empty = await self.client.put(
            "/account/notify",
            json={"importances": []},
            headers=self.headers(),
        )
        self.assertEqual(empty.status_code, 400)
        updated = await self.client.put(
            "/account/notify",
            json={"importances": ["urgent", "normal"]},
            headers=self.headers(),
        )
        self.assertEqual(updated.status_code, 200, updated.json())
        self.assertEqual(updated.json()["notify_importances"], ["urgent", "normal"])
