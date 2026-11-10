from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from api.testing import TestAsyncClient
from user.api import router
from user.utils import get_access_token
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()

PAYLOAD = {
    "email": "newbie@example.com",
    "password": "password1234!",
    "password2": "password1234!",
    "name": "신입",
    "phone_number": "01055556666",
}


class AdminSignupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestAsyncClient(router)
        self.workspace = Workspace.objects.create(name="KOC", slug="koc")
        self.system_admin = User.objects.create_superuser(
            email="root@example.com", password="password1234!", phone_number="01000000001"
        )
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            phone_number="01000000002",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace_admin = User.objects.create_user(
            email="wsadmin@example.com",
            password="password1234!",
            phone_number="01000000003",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            password="password1234!",
            phone_number="01000000004",
            status=User.UserStatusChoice.ACTIVE,
        )
        for user, role in (
            (self.owner, WorkspaceMember.Role.OWNER),
            (self.workspace_admin, WorkspaceMember.Role.ADMIN),
            (self.member, WorkspaceMember.Role.MEMBER),
        ):
            WorkspaceMember.objects.create(workspace=self.workspace, user=user, role=role)

    def headers(self, user):
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_workspace_owner_and_admin_and_system_admin_can_register(self):
        for index, actor in enumerate((self.owner, self.workspace_admin, self.system_admin)):
            payload = {
                **PAYLOAD,
                "email": f"newbie{index}@example.com",
                "phone_number": f"0105555000{index}",
            }
            response = await self.client.post(
                "/admin-signup", json=payload, headers=self.headers(actor)
            )
            self.assertEqual(response.status_code, 201, (index, response.content))
            self.assertEqual(response.json()["email"], payload["email"])

    async def test_created_user_is_active_member_type_with_password(self):
        response = await self.client.post(
            "/admin-signup", json=PAYLOAD, headers=self.headers(self.owner)
        )
        self.assertEqual(response.status_code, 201, response.content)
        user = await User.objects.aget(email=PAYLOAD["email"])
        self.assertEqual(user.status, User.UserStatusChoice.ACTIVE)
        self.assertEqual(user.permission_type, User.UserPermissionTypeChoices.CUSTOMER)
        self.assertEqual(user.name, "신입")
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password(PAYLOAD["password"]))

    async def test_phone_hash_is_not_required_and_phone_is_optional(self):
        payload = {k: v for k, v in PAYLOAD.items() if k != "phone_number"}
        response = await self.client.post(
            "/admin-signup", json=payload, headers=self.headers(self.owner)
        )
        self.assertEqual(response.status_code, 201, response.content)

    async def test_plain_member_is_forbidden(self):
        response = await self.client.post(
            "/admin-signup", json=PAYLOAD, headers=self.headers(self.member)
        )
        self.assertEqual(response.status_code, 403)

    async def test_anonymous_is_unauthorized(self):
        response = await self.client.post("/admin-signup", json=PAYLOAD)
        self.assertEqual(response.status_code, 401)

    async def test_duplicates_are_rejected(self):
        headers = self.headers(self.owner)
        first = await self.client.post("/admin-signup", json=PAYLOAD, headers=headers)
        self.assertEqual(first.status_code, 201)
        same_email = await self.client.post(
            "/admin-signup", json={**PAYLOAD, "phone_number": "01077778888"}, headers=headers
        )
        self.assertEqual(same_email.status_code, 400)
        self.assertEqual(same_email.json()["detail"], "이미 사용중인 이메일입니다.")
        same_phone = await self.client.post(
            "/admin-signup", json={**PAYLOAD, "email": "other@example.com"}, headers=headers
        )
        self.assertEqual(same_phone.status_code, 400)
        self.assertEqual(same_phone.json()["detail"], "이미 사용중인 전화번호입니다.")

    async def test_validation_errors(self):
        headers = self.headers(self.owner)
        mismatch = await self.client.post(
            "/admin-signup", json={**PAYLOAD, "password2": "different1234"}, headers=headers
        )
        self.assertEqual(mismatch.status_code, 400)
        blank_name = await self.client.post(
            "/admin-signup", json={**PAYLOAD, "name": "  "}, headers=headers
        )
        self.assertEqual(blank_name.status_code, 400)
        bad_phone = await self.client.post(
            "/admin-signup", json={**PAYLOAD, "phone_number": "abc"}, headers=headers
        )
        self.assertEqual(bad_phone.status_code, 400)
