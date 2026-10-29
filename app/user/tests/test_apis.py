from django.conf import settings
from django.test import TestCase
from django.contrib.auth import get_user_model

from mcp_server.oauth_server import _token_response
from user.utils import get_access_token
from user.api import router
from django.utils import timezone
from datetime import timedelta
from api.testing import TestAsyncClient
from verification.models import PhonenumberVerification

User = get_user_model()


class TestAuth(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="password1234!",
            phone_number="01011112222",
            type="member",
        )
        self.user2 = User.objects.create_user(
            email="testmember@example.com",
            password="password1234!",
            phone_number="01011112323",
            type="member",
        )
        self.user3 = User.objects.create_user(
            email="updowney@daum.net",
            password="password1234!",
            phone_number="01011112323",
            type="member",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password1234!",
            phone_number="01099999999",
        )
        self.testuser = User.objects.create_user(
            email="testuser2@example.com",
            password="password1234!",
            phone_number="01011113333",
        )
        self.verification = PhonenumberVerification.objects.create(
            phone_number="01012345678",
            code="123456",
            is_verified=True,
            hash="testhash",
        )
        self.verification2 = PhonenumberVerification.objects.create(
            phone_number="01011112222",
            code="123456",
            is_verified=True,
            hash="testhash",
        )

    async def authenticate(
        self, email="testuser@example.com", password="password1234!"
    ):
        data = {
            "email": email,
            "password": password,
        }
        response = await self.client.post("/login", json=data)
        access = response.json().get("access")
        return {"Authorization": f"Bearer {access}"}

    async def authenticate_cookies(
        self, email="testuser@example.com", password="password1234!"
    ):
        data = {
            "email": email,
            "password": password,
        }
        response = await self.client.post("/login", json=data)
        return response.cookies

    async def authenticate_refresh(
        self, email="testuser@example.com", password="password1234!"
    ):
        data = {
            "email": email,
            "password": password,
        }
        response = await self.client.post("/login", json=data)
        return response.json().get("refresh")

    async def test_signup(self):
        """회원가입 테스트"""
        data = {
            "email": "testuser@test.com",
            "password": "password1234!",
            "password2": "password1234!",
            "phone_number": "01012345678",
            "type": "member",
            "phone_hash": self.verification.hash,
        }

        response = await self.client.post("/signup", json=data)
        res_data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", res_data)

    async def test_signup_short_password(self):
        """회원가입 테스트 - 비밀번호 길이 제한 테스트"""
        data = {
            "email": "testuser@test.com",
            "password": "3",
            "password2": "3",
            "phone_number": "01012345678",
            "type": "member",
            "phone_hash": self.verification.hash,
        }

        response = await self.client.post("/signup", json=data)
        res_data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(res_data.get("detail"), "비밀번호는 8자 이상이어야 합니다.")

    async def test_signup_password_mismatch(self):
        """비밀번호와 비밀번호 확인 불일치 테스트"""
        data = {
            "email": "testuser1@example.com",
            "password": "password1234!",
            "password2": "wrongpassword",
            "name": "testuser1",
            "email": "test@test.com",
            "phone_number": "01012345678",
            "phone_hash": self.verification.hash,
        }
        response = await self.client.post("/signup", json=data)
        res_data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(res_data.get("detail"), "비밀번호가 일치하지 않습니다.")

    async def test_signup_email_exist(self):
        """회원가입 : 이미 사용중인 이메일 테스트"""
        data = {
            "email": "testuser@example.com",
            "password": "password1234!",
            "password2": "password1234!",
            "phone_number": "01012345678",
            "type": "member",
            "phone_hash": self.verification.hash,
        }
        response = await self.client.post("/signup", json=data)
        res_data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(res_data.get("detail"), "이미 사용중인 이메일입니다.")

    async def test_signup_phone_number_exist(self):
        """회원가입 : 이미 사용중인 전화번호 테스트"""
        data = {
            "email": "test@test.com",
            "password": "password1234!",
            "password2": "password1234!",
            "phone_number": "01011112222",
            "type": "member",
            "phone_hash": self.verification2.hash,
        }
        response = await self.client.post("/signup", json=data)
        res_data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(res_data.get("detail"), "이미 사용중인 전화번호입니다.")

    async def test_login(self):
        """로그인 테스트"""
        data = {
            "email": "testuser@example.com",
            "password": "password1234!",
        }
        response = await self.client.post("/login", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        # 쿠키 점검
        cookies = response.cookies
        self.assertIn("access", cookies)
        self.assertIn("refresh", cookies)

    async def test_me(self):
        """내 정보 조회 테스트"""
        headers = await self.authenticate()
        response = await self.client.get("/me", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", data)

    async def test_me_guest(self):
        """내 정보 조회 게스트 테스트"""
        response = await self.client.get("/me")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("data"), "guest")

    async def test_me_200_separates_guest_from_member(self):
        """토큰 문제는 400이 아니라 200 게스트이고, 정상 토큰만 회원 본문이다."""
        self.assertEqual((await self.client.get("/me")).json(), {"data": "guest"})
        broken = await self.client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
        self.assertEqual(broken.status_code, 200)
        self.assertEqual(broken.json(), {"data": "guest"})

        expired, _expires = get_access_token(
            {
                "user_id": self.user.id,
                "env": settings.DJANGO_ENV_NAME,
                "exp": int(timezone.now().timestamp()) - 300,
            }
        )
        wrong_aud, _expires = get_access_token(
            {
                "user_id": self.user.id,
                "env": settings.DJANGO_ENV_NAME,
                "aud": "https://evil.example/mcp",
            }
        )
        wrong_env, _expires = get_access_token(
            {
                "user_id": self.user.id,
                "env": "not-this-environment",
            }
        )
        unknown_user, _expires = get_access_token(
            {
                "user_id": 9_999_999,
                "env": settings.DJANGO_ENV_NAME,
            }
        )
        for token in (expired, wrong_aud, wrong_env, unknown_user):
            response = await self.client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json(), {"data": "guest"})

        login_headers = await self.authenticate()
        login_me = await self.client.get("/me", headers=login_headers)
        self.assertEqual(login_me.status_code, 200, login_me.content)
        self.assertEqual(login_me.json()["email"], self.user.email)
        self.assertNotEqual(login_me.json().get("data"), "guest")

        issued = await _token_response(self.user)
        oauth_me = await self.client.get(
            "/me",
            headers={"Authorization": f"Bearer {issued['body']['access_token']}"},
        )
        self.assertEqual(oauth_me.status_code, 200, oauth_me.content)
        self.assertEqual(oauth_me.json()["email"], self.user.email)
        self.assertEqual(oauth_me.json()["id"], self.user.id)
        self.assertNotEqual(oauth_me.json().get("data"), "guest")

    async def test_update_me(self):
        """내 정보 수정 테스트"""
        headers = await self.authenticate()
        data = {
            "email": "update@example.com",
            "nickname": "updateuser",
            "type": "member",
            "push_notification": True,
        }
        response = await self.client.patch("/me", json=data, headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("nickname"), "updateuser")
        self.assertEqual(data.get("type"), "member")
        self.assertEqual(data.get("push_notification"), True)

    async def test_logout(self):
        """로그아웃 테스트 - 쿠키 방식"""
        headers = await self.authenticate()
        refresh = await self.authenticate_refresh()
        response = await self.client.get("/logout", COOKIES={"refresh": refresh})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("detail"), "로그아웃 되었습니다.")

    async def test_logout_cookies(self):
        """로그아웃 테스트 - body 방식"""
        headers = await self.authenticate()
        refresh = await self.authenticate_refresh()
        data = {"refresh": refresh}
        response = await self.client.get("/logout", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("detail"), "로그아웃 되었습니다.")

    async def test_refresh(self):
        """토큰 재발급 테스트 - 쿠키 방식"""
        refresh = await self.authenticate_refresh()
        response = await self.client.post("/refresh", COOKIES={"refresh": refresh})
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.json())
        # 쿠키 점검
        cookies = response.cookies
        self.assertIn("access", cookies)
        self.assertIn("refresh", cookies)

    async def test_refresh_body(self):
        """토큰 재발급 테스트 - body 방식"""
        refresh = await self.authenticate_refresh()
        data = {"refresh": refresh}
        response = await self.client.post("/refresh", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.json())
        # 쿠키 점검
        cookies = response.cookies
        self.assertIn("access", cookies)
        self.assertIn("refresh", cookies)

    async def test_token_verify(self):
        """토큰 검증 테스트"""
        headers = await self.authenticate()
        response = await self.client.get("/verify", headers=headers)
        self.assertEqual(response.status_code, 200)

    async def test_token_verify_invalid(self):
        """토큰 검증 : 유효하지 않은 토큰 테스트"""
        headers = {"Authorization": "Bearer invalidtoken"}
        response = await self.client.get("/verify", headers=headers)
        self.assertEqual(response.status_code, 401)

    async def test_change_password(self):
        """비밀번호 변경 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "password1234!",
            "new_password": "newpassword1234!",
            "new_password_confirm": "newpassword1234!",
        }
        response = await self.client.post(
            "/change-password", json=data, headers=headers
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("detail"), "비밀번호가 변경되었습니다.")

    async def test_change_password_mismatch(self):
        """비밀번호 변경 : 새 비밀번호 불일치 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "password1234!",
            "new_password": "newpassword1234!",
            "new_password_confirm": "wrongpassword",
        }
        response = await self.client.post(
            "/change-password", json=data, headers=headers
        )
        data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("detail"), "새 비밀번호가 일치하지 않습니다."
        )

    async def test_change_password_wrong_password(self):
        """비밀번호 변경 : 현재 비밀번호 불일치 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "wrongpassword",
            "new_password": "newpassword1234!",
            "new_password_confirm": "newpassword1234!",
        }
        response = await self.client.post(
            "/change-password", json=data, headers=headers
        )
        data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("detail"), "비밀번호가 일치하지 않습니다.")

    async def test_change_password_short_password(self):
        """비밀번호 변경 : 비밀번호 길이 제한 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "password1234!",
            "new_password": "short",
            "new_password_confirm": "short",
        }
        response = await self.client.post(
            "/change-password", json=data, headers=headers
        )
        data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("detail"), "비밀번호는 8자 이상이어야 합니다."
        )

    async def test_user_list(self):
        """유저 리스트 조회 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        response = await self.client.get("/list", headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", data)
        self.assertIn("email", data["data"][0])
        self.assertIn("phone_number", data["data"][0])
        self.assertIn("status", data["data"][0])

    async def test_user_admin_update(self):
        """유저 정보 수정 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        data = {
            "phone_number": "01012345678",
        }
        response = await self.client.patch(
            f"/{self.user2.id}", json=data, headers=headers
        )
        self.assertEqual(response.status_code, 200)

    async def test_user_admin_update_withdraw(self):
        """유저 탈퇴 처리 테스트"""
        headers = await self.authenticate(email="admin@example.com")
        data = {
            "status": "W",
            "withdraw_reason": "이유",
        }
        response = await self.client.patch(
            f"/{self.user2.id}", json=data, headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "W")
        self.assertEqual(response.json().get("withdraw_reason"), "이유")

    async def test_user_list_unauthorized(self):
        """관리자 권한 없이 유저 리스트 조회 테스트"""
        headers = await self.authenticate()
        response = await self.client.get("/list", headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("detail"), "Unauthorized")

    async def test_user_withdraw(self):
        """회원 탈퇴 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "password1234!",
            "withdraw_reason": "이유",
        }
        response = await self.client.post("/withdraw", json=data, headers=headers)
        self.assertEqual(response.status_code, 200)

    async def test_user_withdraw_and_restore(self):
        """회원 탈퇴 후 복구 테스트"""
        headers = await self.authenticate()
        data = {
            "password": "password1234!",
            "withdraw_reason": "이유",
        }
        response = await self.client.post("/withdraw", json=data, headers=headers)
        self.assertEqual(response.status_code, 200)

        response = await self.client.post("/restore", json=data, headers=headers)
        self.assertEqual(response.status_code, 200)

    # async def test_password_reset_request(self):
    #     """비밀번호 재설정 요청"""
    #     data = {"email": "updowney@daum.net"}

    #     response = await self.client.post("/reset-password-request", json=data)
    #     data = response.json()
    #     # print("🐍 File: tests/test_apis.py | Line: 393 | setUp ~ data", data)

    #     self.assertEqual(response.status_code, 200)
    #     self.assertIn("message", data)
    #     self.assertEqual(data["message"], "비밀번호 재설정 이메일이 전송되었어요.")
