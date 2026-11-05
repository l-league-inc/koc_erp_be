from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from ninja.testing import TestAsyncClient

from document.storage import block_file_prefix
from notification.models import Notification
from user.utils import get_access_token
from workspace.api import router
from workspace.models import Page, WorkspaceMember
from workspace.seed import seed_koc_workspace

User = get_user_model()


class SafetyApiTests(TestCase):
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
        sales = next(item for item in response.json() if item["slug"] == "sales")
        return sales["id"]

    async def test_revision_restore_keeps_previous_body(self):
        sales_id = await self._sales_id()
        headers = self._headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "개정 대상",
                "blocks": [{"type": "paragraph", "content": {"text": "처음"}}],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        record_id = created.json()["id"]
        block_id = created.json()["blocks"][0]["id"]
        changed = await self.client.patch(
            f"/block/{block_id}",
            json={"content": {"text": "나중"}},
            headers=headers,
        )
        self.assertEqual(changed.status_code, 200, changed.json())

        listed = await self.client.get(f"/record/{record_id}/revision", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertEqual(len(listed.json()), 1)
        self.assertNotIn("body", listed.json()[0])
        self.assertEqual(listed.json()[0]["actor_name"], "박승원")
        revision_id = listed.json()[0]["id"]

        detail = await self.client.get(
            f"/record/{record_id}/revision/{revision_id}",
            headers=headers,
        )
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertEqual(detail.json()["body"]["blocks"][0]["content"]["text"], "처음")

        restored = await self.client.post(
            f"/record/{record_id}/revision/{revision_id}/restore",
            headers=headers,
        )
        self.assertEqual(restored.status_code, 200, restored.json())
        self.assertEqual(restored.json()["blocks"][0]["content"]["text"], "처음")

        again = await self.client.get(f"/record/{record_id}/revision", headers=headers)
        self.assertEqual(len(again.json()), 2)
        newest = await self.client.get(
            f"/record/{record_id}/revision/{again.json()[0]['id']}",
            headers=headers,
        )
        self.assertEqual(newest.json()["body"]["blocks"][0]["content"]["text"], "나중")

    async def test_other_workspace_file_key_is_rejected(self):
        headers = self._headers()
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            uploaded = await self.client.post(
                f"/{self.workspace.id}/block-file",
                json={"file_name": "사진.png"},
                headers=headers,
            )
        self.assertEqual(uploaded.status_code, 200, uploaded.json())
        object_key = uploaded.json()["object_key"]
        self.assertTrue(object_key.startswith(block_file_prefix(self.workspace.id)))
        self.assertNotIn("/documents/", object_key)
        self.assertEqual(uploaded.json()["upload_url"], "https://upload.example/put")

        sales_id = await self._sales_id()
        foreign = f"{block_file_prefix(self.workspace.id + 999)}abc/사진.png"
        rejected = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "다른 경로",
                "blocks": [{"type": "image", "content": {"object_key": foreign}}],
            },
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 400, rejected.json())

        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "비공개 이미지",
                "blocks": [
                    {
                        "type": "image",
                        "content": {"object_key": object_key, "file_name": "사진.png"},
                    }
                ],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        legacy = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "기존 주소",
                "blocks": [{"type": "image", "content": {"url": "https://cdn.example/a.png"}}],
            },
            headers=headers,
        )
        self.assertEqual(legacy.status_code, 201, legacy.json())

        block_id = created.json()["blocks"][0]["id"]
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://download.example/get"
            download = await self.client.post(f"/block/{block_id}/file", headers=self._headers(self.member))
        self.assertEqual(download.status_code, 200, download.json())
        self.assertEqual(download.json()["download_url"], "https://download.example/get")
        self.assertEqual(download.json()["expires_in"], 300)

    async def test_admin_access_blocks_member_writes(self):
        sales_id = await self._sales_id()
        member_headers = self._headers(self.member)
        locked = await self.client.patch(
            f"/database/{sales_id}",
            json={"access": "admin"},
            headers=self._headers(),
        )
        self.assertEqual(locked.status_code, 200, locked.json())
        self.assertEqual(locked.json()["access"], "admin")
        denied_lock = await self.client.patch(
            f"/database/{sales_id}",
            json={"access": "member"},
            headers=member_headers,
        )
        self.assertEqual(denied_lock.status_code, 403)

        denied_record = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "멤버 행"},
            headers=member_headers,
        )
        self.assertEqual(denied_record.status_code, 403)

        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "관리자 행"},
            headers=self._headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        record_id = created.json()["id"]
        visible = await self.client.get(f"/record/{record_id}", headers=member_headers)
        self.assertEqual(visible.status_code, 200)
        comment = await self.client.post(
            f"/record/{record_id}/comment",
            json={"body": "읽기는 됩니다"},
            headers=member_headers,
        )
        self.assertEqual(comment.status_code, 201, comment.json())
        denied_block = await self.client.post(
            f"/record/{record_id}/block",
            json={"type": "paragraph", "content": {"text": "금지"}},
            headers=member_headers,
        )
        self.assertEqual(denied_block.status_code, 403)

        detail = await self.client.get(f"/database/{sales_id}", headers=member_headers)
        prop = next(item for item in detail.json()["properties"] if item["type"] != "title")
        schema = await self.client.patch(
            f"/property/{prop['id']}",
            json={"name": prop["name"]},
            headers=member_headers,
        )
        self.assertEqual(schema.status_code, 200, schema.json())

        page = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "잠긴 문서"},
            headers=self._headers(),
        )
        page_id = page.json()["id"]
        locked_page = await self.client.patch(
            f"/page/{page_id}",
            json={"access": "admin"},
            headers=self._headers(),
        )
        self.assertEqual(locked_page.status_code, 200, locked_page.json())
        opened = await self.client.get(f"/page/{page_id}", headers=member_headers)
        self.assertEqual(opened.status_code, 200)
        denied_page_block = await self.client.post(
            f"/page/{page_id}/block",
            json={"type": "paragraph", "content": {"text": "금지"}},
            headers=member_headers,
        )
        self.assertEqual(denied_page_block.status_code, 403)


class MentionSafetyTests(TransactionTestCase):
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

    async def test_only_new_user_mentions_notify(self):
        sales = await self.client.get("/database", headers=self._headers())
        sales_id = next(item["id"] for item in sales.json() if item["slug"] == "sales")
        page = await sync_to_async(Page.objects.filter(workspace=self.workspace).first)()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "멘션 대상",
                "blocks": [{"type": "paragraph", "content": {"text": "시작"}}],
            },
            headers=self._headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        block_id = created.json()["blocks"][0]["id"]
        record_id = created.json()["id"]

        page_only = await self.client.patch(
            f"/block/{block_id}",
            json={
                "content": {
                    "rich_text": [
                        {"text": "페이지", "mention": {"type": "page", "page_id": page.id}},
                        {"text": "행", "mention": {"type": "record", "record_id": record_id}},
                    ]
                }
            },
            headers=self._headers(),
        )
        self.assertEqual(page_only.status_code, 200, page_only.json())
        self.assertEqual(await sync_to_async(Notification.objects.count)(), 0)

        mentioned = await self.client.patch(
            f"/block/{block_id}",
            json={
                "content": {
                    "rich_text": [
                        {"text": "김멤버", "mention": {"type": "user", "user_id": self.member.id}},
                        {"text": "페이지", "mention": {"type": "page", "page_id": page.id}},
                    ]
                }
            },
            headers=self._headers(),
        )
        self.assertEqual(mentioned.status_code, 200, mentioned.json())
        notes = await sync_to_async(list)(Notification.objects.filter(user=self.member))
        self.assertEqual(len(notes), 1)
        self.assertLessEqual(len(notes[0].message), 200)
        self.assertEqual(
            notes[0].metadata,
            {
                "kind": "mention",
                "workspace_id": self.workspace.id,
                "target": "record",
                "target_id": record_id,
                "block_id": block_id,
            },
        )

        again = await self.client.patch(
            f"/block/{block_id}",
            json={
                "content": {
                    "rich_text": [
                        {"text": "김멤버 다시", "mention": {"type": "user", "user_id": self.member.id}},
                        {"text": "나", "mention": {"type": "user", "user_id": self.user.id}},
                    ]
                }
            },
            headers=self._headers(),
        )
        self.assertEqual(again.status_code, 200, again.json())
        self.assertEqual(await sync_to_async(Notification.objects.filter(user=self.member).count)(), 1)
        self.assertEqual(await sync_to_async(Notification.objects.filter(user=self.user).count)(), 0)
