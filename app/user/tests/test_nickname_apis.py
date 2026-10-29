from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from api.testing import TestAsyncClient
from user.api import router
from user.nickname_utils import is_missing_nickname
from user.tests.test_nickname_utils import assert_nickname_format
from verification.models import PhonenumberVerification

User = get_user_model()


class TestNicknameAPIs(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.verification = PhonenumberVerification.objects.create(
            phone_number="01099887766",
            code="123456",
            is_verified=True,
            hash="nickname-test-hash",
        )
        self.user = User.objects.create_user(
            email="nickname-user@example.com",
            password="password1234!",
            phone_number="01011114444",
            type="member",
        )
        self.partner = User.objects.create_user(
            email="partner@example.com",
            password="password1234!",
            phone_number="01011115555",
            type="member",
        )

    async def authenticate(self, email: str = "nickname-user@example.com") -> dict:
        response = await self.client.post(
            "/login",
            json={"email": email, "password": "password1234!"},
        )
        access = response.json().get("access")
        return {"Authorization": f"Bearer {access}"}

    async def test_signup_response_includes_auto_generated_nickname(self):
        response = await self.client.post(
            "/signup",
            json={
                "email": "signup-nickname@example.com",
                "password": "password1234!",
                "password2": "password1234!",
                "phone_number": self.verification.phone_number,
                "type": "member",
                "phone_hash": self.verification.hash,
            },
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("nickname", data)
        self.assertFalse(is_missing_nickname(data["nickname"]))
        assert_nickname_format(self, data["nickname"])

        created_user = await User.objects.aget(email="signup-nickname@example.com")
        self.assertEqual(created_user.nickname, data["nickname"])

    async def test_me_returns_nickname(self):
        headers = await self.authenticate()
        response = await self.client.get("/me", headers=headers)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("nickname", data)
        self.assertFalse(is_missing_nickname(data["nickname"]))
        self.assertEqual(data["nickname"], self.user.nickname)

    async def test_update_me_can_change_nickname(self):
        headers = await self.authenticate()
        response = await self.client.patch(
            "/me",
            json={"nickname": "변경한닉네임"},
            headers=headers,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["nickname"], "변경한닉네임")

        await self.user.arefresh_from_db()
        self.assertEqual(self.user.nickname, "변경한닉네임")

    async def test_update_me_rejects_duplicate_nickname(self):
        headers = await self.authenticate()
        response = await self.client.patch(
            "/me",
            json={"nickname": self.partner.nickname},
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "이미 사용중인 닉네임입니다.")

        await self.user.arefresh_from_db()
        self.assertNotEqual(self.user.nickname, self.partner.nickname)

    async def test_update_me_allows_keeping_own_nickname(self):
        headers = await self.authenticate()
        response = await self.client.patch(
            "/me",
            json={"nickname": self.user.nickname},
            headers=headers,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["nickname"], self.user.nickname)

    async def test_update_me_rejects_blank_nickname(self):
        headers = await self.authenticate()
        response = await self.client.patch(
            "/me",
            json={"nickname": "   "},
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "닉네임을 입력해주세요.")
