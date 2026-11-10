from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()
Role = WorkspaceMember.Role


class WorkspaceMemberManageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestAsyncClient(router)
        self.workspace = Workspace.objects.create(name="KOC", slug="koc")
        self.owner = self._user("owner@example.com", Role.OWNER)
        self.admin = self._user("admin@example.com", Role.ADMIN)
        self.member = self._user("member@example.com", Role.MEMBER)
        self.newcomer = self._user("new@example.com", None)

    def _user(self, email: str, role: str | None):
        user = User.objects.create_user(
            email=email,
            password="password1234!",
            name=email.split("@")[0],
            phone_number=f"010{User.objects.count():08d}",
            status=User.UserStatusChoice.ACTIVE,
        )
        if role:
            WorkspaceMember.objects.create(workspace=self.workspace, user=user, role=role)
        return user

    def headers(self, user):
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    def url(self, suffix: str = "") -> str:
        return f"/{self.workspace.id}/member{suffix}"

    async def test_manager_lists_member_details(self):
        response = await self.client.get(self.url("/manage"), headers=self.headers(self.admin))
        self.assertEqual(response.status_code, 200, response.content)
        by_id = {item["user_id"]: item for item in response.json()}
        self.assertEqual(by_id[self.member.id]["email"], "member@example.com")
        self.assertEqual(by_id[self.owner.id]["role"], "owner")

    async def test_member_cannot_manage(self):
        headers = self.headers(self.member)
        listed = await self.client.get(self.url("/manage"), headers=headers)
        self.assertEqual(listed.status_code, 403)
        added = await self.client.post(
            self.url(), json={"user_id": self.newcomer.id}, headers=headers
        )
        self.assertEqual(added.status_code, 403)

    async def test_admin_adds_member_by_user_id_and_email(self):
        headers = self.headers(self.admin)
        response = await self.client.post(
            self.url(), json={"user_id": self.newcomer.id}, headers=headers
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["role"], "member")
        self.assertEqual(response.json()["email"], "new@example.com")

        again = await self.client.post(
            self.url(), json={"email": "new@example.com"}, headers=headers
        )
        self.assertEqual(again.status_code, 400)

        other = await sync_create_user("other@example.com")
        by_email = await self.client.post(
            self.url(), json={"email": other.email}, headers=headers
        )
        self.assertEqual(by_email.status_code, 201, by_email.content)

    async def test_add_requires_exactly_one_identifier(self):
        headers = self.headers(self.owner)
        neither = await self.client.post(self.url(), json={}, headers=headers)
        self.assertEqual(neither.status_code, 400)
        both = await self.client.post(
            self.url(),
            json={"user_id": self.newcomer.id, "email": self.newcomer.email},
            headers=headers,
        )
        self.assertEqual(both.status_code, 400)

    async def test_add_unknown_or_withdrawn_user_is_404(self):
        headers = self.headers(self.owner)
        missing = await self.client.post(self.url(), json={"user_id": 999999}, headers=headers)
        self.assertEqual(missing.status_code, 404)
        self.newcomer.status = User.UserStatusChoice.WITHDRAW
        await self.newcomer.asave()
        withdrawn = await self.client.post(
            self.url(), json={"user_id": self.newcomer.id}, headers=headers
        )
        self.assertEqual(withdrawn.status_code, 404)

    async def test_invalid_role_is_rejected(self):
        response = await self.client.post(
            self.url(),
            json={"user_id": self.newcomer.id, "role": "boss"},
            headers=self.headers(self.owner),
        )
        self.assertEqual(response.status_code, 400)

    async def test_only_owner_grants_privileged_roles(self):
        denied = await self.client.post(
            self.url(),
            json={"user_id": self.newcomer.id, "role": "admin"},
            headers=self.headers(self.admin),
        )
        self.assertEqual(denied.status_code, 403)
        allowed = await self.client.post(
            self.url(),
            json={"user_id": self.newcomer.id, "role": "admin"},
            headers=self.headers(self.owner),
        )
        self.assertEqual(allowed.status_code, 201, allowed.content)
        self.assertEqual(allowed.json()["role"], "admin")

    async def test_admin_cannot_promote_or_touch_admin(self):
        headers = self.headers(self.admin)
        promote = await self.client.patch(
            self.url(f"/{self.member.id}"), json={"role": "admin"}, headers=headers
        )
        self.assertEqual(promote.status_code, 403)
        demote_owner = await self.client.patch(
            self.url(f"/{self.owner.id}"), json={"role": "member"}, headers=headers
        )
        self.assertEqual(demote_owner.status_code, 403)
        remove_owner = await self.client.delete(self.url(f"/{self.owner.id}"), headers=headers)
        self.assertEqual(remove_owner.status_code, 403)

    async def test_owner_changes_role(self):
        response = await self.client.patch(
            self.url(f"/{self.member.id}"),
            json={"role": "admin"},
            headers=self.headers(self.owner),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role"], "admin")
        stored = await WorkspaceMember.objects.aget(user=self.member)
        self.assertEqual(stored.role, "admin")

    async def test_last_owner_is_protected(self):
        headers = self.headers(self.owner)
        demote = await self.client.patch(
            self.url(f"/{self.owner.id}"), json={"role": "admin"}, headers=headers
        )
        self.assertEqual(demote.status_code, 400)
        remove = await self.client.delete(self.url(f"/{self.owner.id}"), headers=headers)
        self.assertEqual(remove.status_code, 400)

    async def test_second_owner_allows_owner_change(self):
        await self.client.patch(
            self.url(f"/{self.admin.id}"),
            json={"role": "owner"},
            headers=self.headers(self.owner),
        )
        demote = await self.client.patch(
            self.url(f"/{self.owner.id}"),
            json={"role": "member"},
            headers=self.headers(self.admin),
        )
        self.assertEqual(demote.status_code, 200, demote.content)

    async def test_admin_removes_member_and_can_readd(self):
        headers = self.headers(self.admin)
        response = await self.client.delete(self.url(f"/{self.member.id}"), headers=headers)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            await WorkspaceMember.objects.filter(
                workspace=self.workspace, user=self.member
            ).aexists()
        )
        user_still_there = await User.objects.filter(id=self.member.id).aexists()
        self.assertTrue(user_still_there)
        readd = await self.client.post(
            self.url(), json={"user_id": self.member.id}, headers=headers
        )
        self.assertEqual(readd.status_code, 201, readd.content)

    async def test_remove_unknown_member_is_404(self):
        response = await self.client.delete(
            self.url(f"/{self.newcomer.id}"), headers=self.headers(self.owner)
        )
        self.assertEqual(response.status_code, 404)

    async def test_removed_member_loses_access(self):
        await self.client.delete(self.url(f"/{self.member.id}"), headers=self.headers(self.owner))
        response = await self.client.get(self.url(), headers=self.headers(self.member))
        self.assertEqual(response.status_code, 403)


async def sync_create_user(email: str):
    from asgiref.sync import sync_to_async

    return await sync_to_async(User.objects.create_user)(
        email=email,
        password="password1234!",
        status=User.UserStatusChoice.ACTIVE,
    )
