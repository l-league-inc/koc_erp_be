from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from mail.api import router
from mail.crypto import decrypt_secret
from mail.models import UserMailAccount
from user.utils import get_access_token

User = get_user_model()


class MailApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="mail-user@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )

    def headers(self):
        token, _expires = get_access_token(
            {"user_id": self.user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_account_empty_then_upsert_encrypts_password(self):
        empty = await self.client.get("/account", headers=self.headers())
        self.assertEqual(empty.status_code, 200, empty.json())
        self.assertFalse(empty.json()["configured"])

        with patch("mail.service.daum.test_connection") as mocked:
            saved = await self.client.put(
                "/account",
                json={"username": "daumid", "app_password": "plain-app-password"},
                headers=self.headers(),
            )
        self.assertEqual(saved.status_code, 200, saved.json())
        mocked.assert_called_once_with("daumid", "plain-app-password")
        body = saved.json()
        self.assertTrue(body["configured"])
        self.assertTrue(body["is_verified"])
        self.assertEqual(body["username"], "daumid")
        self.assertNotIn("plain-app-password", str(body))
        self.assertNotIn("app_password", body)

        account = await UserMailAccount.objects.aget(user=self.user)
        self.assertNotEqual(account.password_encrypted, "plain-app-password")
        self.assertNotIn("plain-app-password", account.password_encrypted)
        self.assertEqual(decrypt_secret(account.password_encrypted), "plain-app-password")

    async def test_list_get_send_use_service_client(self):
        with patch("mail.service.daum.test_connection"):
            await self.client.put(
                "/account",
                json={"username": "daumid", "app_password": "secret"},
                headers=self.headers(),
            )

        with patch(
            "mail.service.daum.list_messages",
            return_value=[
                {
                    "uid": "1",
                    "folder": "INBOX",
                    "subject": "hello",
                    "sender": "a@example.com",
                    "date": None,
                    "flags": ["unseen"],
                    "snippet": "hi",
                }
            ],
        ) as listed:
            response = await self.client.get(
                "/messages?unread_only=true&limit=5",
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()[0]["uid"], "1")
        listed.assert_called_once()
        kwargs = listed.call_args.kwargs
        self.assertEqual(kwargs["folder"], "INBOX")
        self.assertEqual(kwargs["limit"], 5)
        self.assertTrue(kwargs["unread_only"])

        with patch(
            "mail.service.daum.get_message",
            return_value={
                "uid": "1",
                "folder": "INBOX",
                "subject": "hello",
                "sender": "a@example.com",
                "to": "daumid@daum.net",
                "cc": "",
                "date": None,
                "flags": ["unseen"],
                "body": "본문",
            },
        ) as fetched:
            detail = await self.client.get("/messages/1", headers=self.headers())
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertEqual(detail.json()["body"], "본문")
        fetched.assert_called_once()

        with patch(
            "mail.service.daum.send_message",
            return_value={
                "sender": "daumid@daum.net",
                "to": ["b@example.com"],
                "cc": [],
                "bcc": [],
                "subject": "회신",
            },
        ) as sent:
            result = await self.client.post(
                "/send",
                json={
                    "to": ["b@example.com"],
                    "subject": "회신",
                    "body": "확인했습니다.",
                },
                headers=self.headers(),
            )
        self.assertEqual(result.status_code, 200, result.json())
        self.assertEqual(result.json()["subject"], "회신")
        sent.assert_called_once()

    async def test_delete_account(self):
        with patch("mail.service.daum.test_connection"):
            await self.client.put(
                "/account",
                json={"username": "daumid", "app_password": "secret"},
                headers=self.headers(),
            )
        deleted = await self.client.delete("/account", headers=self.headers())
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(await UserMailAccount.objects.filter(user=self.user).aexists())
