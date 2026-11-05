from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import WorkspaceMember
from workspace.seed import seed_koc_workspace

User = get_user_model()


class EditingExperienceTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )
        self.workspace = seed_koc_workspace()
        self.member = User.objects.create_user(
            email="member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="김멤버",
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=WorkspaceMember.Role.MEMBER,
        )

    def _headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def _sales_id(self) -> int:
        response = await self.client.get("/database", headers=self._headers())
        return next(item["id"] for item in response.json() if item["slug"] == "sales")

    async def test_search_uses_visible_text_only(self):
        sales_id = await self._sales_id()
        headers = self._headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "검색 대상",
                "blocks": [
                    {
                        "type": "paragraph",
                        "content": {
                            "rich_text": [
                                {
                                    "text": "연차 규정",
                                    "annotations": {"bold": True},
                                }
                            ]
                        },
                    },
                    {"type": "math_equation", "content": {"formula": "E=mc^2"}},
                    {
                        "type": "image",
                        "content": {
                            "url": "https://cdn.example/secret-path.png",
                            "file_name": "휴가사진.png",
                        },
                    },
                ],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())

        found = await self.client.post(
            "/query",
            json={"database_slug": "sales", "q": "연차 규정"},
            headers=headers,
        )
        self.assertEqual(found.json()["data"][0]["title"], "검색 대상")
        formula = await self.client.post(
            "/query",
            json={"database_slug": "sales", "q": "E=mc^2"},
            headers=headers,
        )
        self.assertEqual(formula.json()["data"][0]["title"], "검색 대상")
        missed = await self.client.post(
            "/query",
            json={"database_slug": "sales", "q": "bold"},
            headers=headers,
        )
        self.assertEqual(missed.json()["data"], [])
        hidden_url = await self.client.post(
            "/query",
            json={"database_slug": "sales", "q": "secret-path"},
            headers=headers,
        )
        self.assertEqual(hidden_url.json()["data"], [])

        page = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "수식 문서"},
            headers=headers,
        )
        await self.client.post(
            f"/page/{page.json()['id']}/block",
            json={"type": "math_equation", "content": {"formula": "a^2+b^2"}},
            headers=headers,
        )
        searched = await self.client.post(
            "/search",
            json={"workspace_id": self.workspace.id, "q": "a^2+b^2"},
            headers=headers,
        )
        self.assertEqual(searched.status_code, 200, searched.json())
        self.assertTrue(any(item["kind"] == "page" and item["title"] == "수식 문서" for item in searched.json()["data"]))
        file_name = await self.client.post(
            "/search",
            json={"workspace_id": self.workspace.id, "q": "휴가사진"},
            headers=headers,
        )
        self.assertTrue(any(item["title"] == "검색 대상" for item in file_name.json()["data"]))

    async def test_block_comment_thread_and_resolve_for_locked_document(self):
        sales_id = await self._sales_id()
        locked = await self.client.patch(
            f"/database/{sales_id}",
            json={"access": "admin"},
            headers=self._headers(),
        )
        self.assertEqual(locked.status_code, 200, locked.json())
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "댓글 행",
                "blocks": [{"type": "paragraph", "content": {"text": "본문"}}],
            },
            headers=self._headers(),
        )
        block_id = created.json()["blocks"][0]["id"]
        member_headers = self._headers(self.member)
        denied_write = await self.client.patch(
            f"/block/{block_id}",
            json={"content": {"text": "수정"}},
            headers=member_headers,
        )
        self.assertEqual(denied_write.status_code, 403)

        comment = await self.client.post(
            f"/block/{block_id}/comment",
            json={"body": "이 문단 확인"},
            headers=member_headers,
        )
        self.assertEqual(comment.status_code, 201, comment.json())
        comment_id = comment.json()["id"]
        reply = await self.client.post(
            f"/block/{block_id}/comment",
            json={"body": "확인했습니다", "parent_id": comment_id},
            headers=self._headers(),
        )
        self.assertEqual(reply.status_code, 201, reply.json())
        nested = await self.client.post(
            f"/block/{block_id}/comment",
            json={"body": "한 단계 더", "parent_id": reply.json()["id"]},
            headers=self._headers(),
        )
        self.assertEqual(nested.status_code, 400)
        reply_resolve = await self.client.post(
            f"/block-comment/{reply.json()['id']}/resolve",
            headers=self._headers(),
        )
        self.assertEqual(reply_resolve.status_code, 400)

        member_resolve = await self.client.post(
            f"/block-comment/{comment_id}/resolve",
            headers=member_headers,
        )
        self.assertEqual(member_resolve.status_code, 200, member_resolve.json())
        self.assertIsNotNone(member_resolve.json()["resolved_at"])
        cleared = await self.client.post(
            f"/block-comment/{comment_id}/unresolve",
            headers=self._headers(),
        )
        self.assertEqual(cleared.status_code, 200, cleared.json())
        self.assertIsNone(cleared.json()["resolved_at"])
        listed = await self.client.get(f"/block/{block_id}/comment", headers=member_headers)
        self.assertEqual(len(listed.json()), 2)
