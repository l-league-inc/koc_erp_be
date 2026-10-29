from django.test import TestCase
from django.contrib.auth import get_user_model
from verification.api import router
from django.utils import timezone
from datetime import timedelta
from api.testing import TestAsyncClient
from verification.models import (
    PhonenumberVerification,
    UsernamePhoneVerification,
    PasswordPhoneVerification,
)


User = get_user_model()


class TestVerification(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="password1234!",
            phone_number="01011111111",
            type="member",
        )
        self.user2 = User.objects.create_user(
            email="testuser2@example.com",
            password="password1234!",
            phone_number="01041362245",
            type="member",
            login_method="email",
        )

    # async def test_phone_verification_request(self):
    #     """휴대폰 인증 코드 요청"""
    #     response = await self.client.post(
    #         "/phone", json={"phone_number": "01041362245"}
    #     )
    #     data = response.json()
    #     self.assertEqual(response.status_code, 500)
    #     self.assertEqual(
    #         response.json(),
    #         {"detail": "알림톡 메시지 전송에 실패했습니다. err_code : -101 인증오류입니다.-IP"},
    #     )

    async def test_phone_verification_check(self):
        """휴대폰 인증 코드 확인"""
        response = await self.client.post(
            "/phone", json={"phone_number": "01099999999"}
        )
        v = await PhonenumberVerification.objects.filter(
            phone_number="01099999999"
        ).afirst()
        response = await self.client.post(
            "/phone-check", json={"phone_number": "01099999999", "code": v.code}
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)

    async def test_username_phone_verification(self):
        """아이디 찾기 휴대폰 인증"""
        response = await self.client.post(
            "/email-phone", json={"phone_number": "01041362245"}
        )
        data = response.json()
        # print("🐍 File: tests/test_apis.py | Line: 69 | setUp ~ data", data)
        self.assertEqual(response.status_code, 200)

    async def test_username_phone_verification_check(self):
        """아이디 찾기 휴대폰 인증 코드 확인"""
        response = await self.client.post(
            "/email-phone", json={"phone_number": "01041362245"}
        )
        v = await UsernamePhoneVerification.objects.filter(user=self.user2).afirst()
        response = await self.client.post(
            "/email-phone-check",
            json={"phone_number": "01041362245", "code": v.code},
        )
        data = response.json()
        # print("🐍 File: tests/test_apis.py | Line: 85 | setUp ~ data", data)
        self.assertEqual(response.status_code, 200)

    async def test_password_phone_verification(self):
        """비밀번호 변경 휴대폰 인증"""
        response = await self.client.post(
            "/password-phone",
            json={
                "phone_number": "01041362245",
                "email": self.user2.email,
            },
        )
        data = response.json()
        # print("🐍 File: tests/test_apis.py | Line: 97 | setUp ~ data", data)
        self.assertEqual(response.status_code, 200)

    async def test_password_phone_verification_check(self):
        """비밀번호 변경 휴대폰 인증 코드 확인"""
        response = await self.client.post(
            "/password-phone",
            json={
                "phone_number": "01041362245",
                "email": self.user2.email,
            },
        )
        self.assertEqual(response.status_code, 200)
        v = await PasswordPhoneVerification.objects.filter(user=self.user2).afirst()
        response = await self.client.post(
            "/password-phone-check",
            json={
                "phone_number": "01041362245",
                "code": v.code,
                "email": self.user2.email,
            },
        )
        data = response.json()
        # print("🐍 File: tests/test_apis.py | Line: 113 | setUp ~ data", data)
        self.assertEqual(response.status_code, 200)

        v = await PasswordPhoneVerification.objects.filter(user=self.user2).afirst()
        response = await self.client.post(
            "/password-phone-change",
            json={
                "phone_number": "01041362245",
                "phone_hash": v.hash,
                "new_password": "newpassword1234!",
                "new_password_confirm": "newpassword1234!",
            },
        )
        data = response.json()
        # print("🐍 File: tests/test_apis.py | Line: 126 | setUp ~ data", data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["message"], "비밀번호가 성공적으로 변경되었습니다.")
