import jwt
from datetime import datetime, timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from unittest.mock import Mock
from api.security import JWTAuth, ActiveUserAuth, AdminAuth


User = get_user_model()


class TestJWTAuth(TestCase):
    """JWT 인증 테스트"""

    def setUp(self):
        """테스트 사용자 및 JWT 인증 인스턴스 생성"""
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
        self.jwt_auth = JWTAuth()
        self.active_user_auth = ActiveUserAuth()
        self.admin_auth = AdminAuth()

    def create_token(self, user_id, exp_delta=None, env=None):
        """JWT 토큰 생성 헬퍼 함수"""
        if exp_delta is None:
            exp_delta = timedelta(hours=1)

        exp = timezone.now() + exp_delta

        payload = {
            "user_id": user_id,
            "env": env or settings.DJANGO_ENV_NAME,
            "exp": exp.timestamp(),
        }

        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    def create_request(self, token=None, cookie_token=None):
        """HTTP 요청 Mock 객체 생성"""
        request = Mock(spec=HttpRequest)
        headers = {}
        cookies = {}

        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie_token:
            cookies["access"] = cookie_token

        request.headers = headers
        request.COOKIES = cookies
        return request

    async def test_valid_token_authentication(self):
        """유효한 토큰으로 인증 성공"""
        token = self.create_token(self.user.id)
        request = self.create_request(token=token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.id, self.user.id)
        self.assertEqual(authenticated_user.email, self.user.email)

    async def test_expired_token_authentication(self):
        """만료된 토큰으로 인증 실패"""
        # 1시간 전에 만료된 토큰
        expired_token = self.create_token(self.user.id, exp_delta=timedelta(hours=-1))
        request = self.create_request(token=expired_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_expired_token_with_jwt_exception(self):
        """만료된 토큰이 jwt.ExpiredSignatureError를 발생시키는지 확인"""
        # 명시적으로 만료된 토큰 생성
        exp = timezone.now() - timedelta(days=1)
        payload = {
            "user_id": self.user.id,
            "env": settings.DJANGO_ENV_NAME,
            "exp": exp.timestamp(),
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

        # jwt.decode()가 ExpiredSignatureError를 발생시키는지 확인
        with self.assertRaises(jwt.ExpiredSignatureError):
            jwt.decode(
                expired_token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_signature": True, "verify_exp": True},
            )

    async def test_just_expired_token(self):
        """방금 만료된 토큰 (경계값 테스트)"""
        # 1초 전에 만료
        expired_token = self.create_token(self.user.id, exp_delta=timedelta(seconds=-1))
        request = self.create_request(token=expired_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_about_to_expire_token(self):
        """곧 만료될 토큰 (아직 유효함)"""
        # 5초 후 만료
        almost_expired_token = self.create_token(
            self.user.id, exp_delta=timedelta(seconds=5)
        )
        request = self.create_request(token=almost_expired_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.id, self.user.id)

    async def test_token_without_expiration(self):
        """만료 시간이 없는 토큰"""
        payload = {
            "user_id": self.user.id,
            "env": settings.DJANGO_ENV_NAME,
            # exp 필드 없음
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        request = self.create_request(token=token)

        authenticated_user = await self.jwt_auth(request)

        # exp가 없으면 jwt.decode()에서 예외 발생하여 인증 실패
        self.assertIsNone(authenticated_user)

    async def test_invalid_token_format(self):
        """잘못된 형식의 토큰"""
        invalid_token = "invalid.token.format"
        request = self.create_request(token=invalid_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_token_with_wrong_signature(self):
        """잘못된 시크릿 키로 생성된 토큰"""
        exp = timezone.now() + timedelta(hours=1)
        payload = {
            "user_id": self.user.id,
            "env": settings.DJANGO_ENV_NAME,
            "exp": exp.timestamp(),
        }
        wrong_token = jwt.encode(payload, "wrong_secret_key", algorithm="HS256")
        request = self.create_request(token=wrong_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_token_with_wrong_environment(self):
        """다른 환경의 토큰"""
        token = self.create_token(self.user.id, env="production")
        request = self.create_request(token=token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_token_with_nonexistent_user(self):
        """존재하지 않는 사용자의 토큰"""
        token = self.create_token(user_id=99999)
        request = self.create_request(token=token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_token_from_cookie(self):
        """쿠키에서 토큰 읽기"""
        token = self.create_token(self.user.id)
        request = self.create_request(cookie_token=token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.id, self.user.id)

    async def test_expired_token_from_cookie(self):
        """쿠키의 만료된 토큰"""
        expired_token = self.create_token(self.user.id, exp_delta=timedelta(hours=-1))
        request = self.create_request(cookie_token=expired_token)

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_no_token_provided(self):
        """토큰이 제공되지 않음"""
        request = self.create_request()

        authenticated_user = await self.jwt_auth(request)

        self.assertIsNone(authenticated_user)


class TestActiveUserAuth(TestCase):
    """활성 사용자 인증 테스트"""

    def setUp(self):
        self.active_user = User.objects.create_user(
            email="active@example.com",
            password="password1234!",
            phone_number="01011112222",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.suspended_user = User.objects.create_user(
            email="suspended@example.com",
            password="password1234!",
            phone_number="01011113333",
            status=User.UserStatusChoice.SUSPENDED,
        )
        self.withdrawn_user = User.objects.create_user(
            email="withdrawn@example.com",
            password="password1234!",
            phone_number="01011114444",
            status=User.UserStatusChoice.WITHDRAW,
            withdraw_at=timezone.now(),
        )
        self.active_user_auth = ActiveUserAuth()

    def create_token(self, user_id, exp_delta=timedelta(hours=1)):
        exp = timezone.now() + exp_delta
        payload = {
            "user_id": user_id,
            "env": settings.DJANGO_ENV_NAME,
            "exp": exp.timestamp(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    def create_request(self, token):
        request = Mock(spec=HttpRequest)
        request.headers = {"Authorization": f"Bearer {token}"}
        request.COOKIES = {}
        return request

    async def test_active_user_authentication(self):
        """활성 사용자 인증 성공"""
        token = self.create_token(self.active_user.id)
        request = self.create_request(token)

        authenticated_user = await self.active_user_auth(request)

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.id, self.active_user.id)

    async def test_suspended_user_authentication(self):
        """정지된 사용자 인증 실패"""
        token = self.create_token(self.suspended_user.id)
        request = self.create_request(token)

        from ninja.errors import HttpError

        with self.assertRaises(HttpError) as context:
            await self.active_user_auth(request)

        self.assertEqual(context.exception.status_code, 403)

    async def test_expired_token_for_active_user(self):
        """활성 사용자의 만료된 토큰"""
        expired_token = self.create_token(
            self.active_user.id, exp_delta=timedelta(hours=-1)
        )
        request = self.create_request(expired_token)

        authenticated_user = await self.active_user_auth(request)

        self.assertIsNone(authenticated_user)


class TestAdminAuth(TestCase):
    """관리자 인증 테스트"""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password1234!",
            phone_number="01099999999",
        )
        self.regular_user = User.objects.create_user(
            email="user@example.com",
            password="password1234!",
            phone_number="01011112222",
        )
        self.admin_auth = AdminAuth()

    def create_token(self, user_id, exp_delta=timedelta(hours=1)):
        exp = timezone.now() + exp_delta
        payload = {
            "user_id": user_id,
            "env": settings.DJANGO_ENV_NAME,
            "exp": exp.timestamp(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    def create_request(self, token):
        request = Mock(spec=HttpRequest)
        request.headers = {"Authorization": f"Bearer {token}"}
        request.COOKIES = {}
        return request

    async def test_admin_authentication(self):
        """관리자 인증 성공"""
        token = self.create_token(self.admin.id)
        request = self.create_request(token)

        authenticated_user = await self.admin_auth(request)

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.id, self.admin.id)

    async def test_regular_user_admin_authentication(self):
        """일반 사용자로 관리자 인증 실패"""
        token = self.create_token(self.regular_user.id)
        request = self.create_request(token)

        authenticated_user = await self.admin_auth(request)

        self.assertIsNone(authenticated_user)

    async def test_expired_admin_token(self):
        """관리자의 만료된 토큰"""
        expired_token = self.create_token(self.admin.id, exp_delta=timedelta(hours=-1))
        request = self.create_request(expired_token)

        authenticated_user = await self.admin_auth(request)

        self.assertIsNone(authenticated_user)
