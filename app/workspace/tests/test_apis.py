from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import Block, Database, Property, RecordActivity, Workspace, WorkspaceMember
from workspace.seed import seed_koc_workspace

User = get_user_model()


class WorkspaceApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        seed_koc_workspace()
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )

    def headers(self, user=None, *, mcp=False):
        user = user or self.user
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        data = {"Authorization": f"Bearer {token}"}
        if mcp:
            data["X-KOC-Client"] = "mcp"
        return data

    async def _sales_id(self) -> int:
        response = await self.client.get("/database", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        sales = next(item for item in response.json() if item["slug"] == "sales")
        return sales["id"]

    async def test_outsider_cannot_read_database(self):
        sales_id = await self._sales_id()
        response = await self.client.get(
            f"/database/{sales_id}",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(response.status_code, 403)

    async def test_invalid_select_is_rejected(self):
        sales_id = await self._sales_id()
        response = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "잘못된 상태", "values": {"status": "없는값"}},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    async def test_query_filters_status(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "A/S 접수",
                "values": {"status": "접수", "kind": "A/S"},
                "blocks": [{"type": "paragraph", "content": {"text": "방문 요청"}}],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertEqual(created.json()["blocks"][0]["content"]["text"], "방문 요청")
        other = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "견적 진행", "values": {"status": "진행 중", "kind": "견적"}},
            headers=headers,
        )
        self.assertEqual(other.status_code, 201, other.json())

        queried = await self.client.post(
            "/query",
            json={
                "database_slug": "sales",
                "filters": [{"property": "status", "op": "eq", "value": "접수"}],
            },
            headers=headers,
        )
        self.assertEqual(queried.status_code, 200, queried.json())
        titles = [item["title"] for item in queried.json()["data"]]
        self.assertEqual(titles, ["A/S 접수"])

        activity = await sync_to_async(RecordActivity.objects.get)(
            record_id=created.json()["id"]
        )
        self.assertEqual(activity.source, RecordActivity.Source.USER)
        self.assertEqual(activity.action, RecordActivity.Action.CREATED)

    async def test_mcp_update_is_marked(self):
        sales_id = await self._sales_id()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "견적 초안", "values": {"status": "접수", "kind": "견적"}},
            headers=self.headers(mcp=True),
        )
        self.assertEqual(created.status_code, 201, created.json())
        record_id = created.json()["id"]
        updated = await self.client.patch(
            f"/record/{record_id}",
            json={"values": {"status": "진행 중"}},
            headers=self.headers(mcp=True),
        )
        self.assertEqual(updated.status_code, 200, updated.json())
        self.assertEqual(updated.json()["values"]["status"], "진행 중")
        self.assertEqual(updated.json()["title"], "견적 초안")
        sources = await sync_to_async(list)(
            RecordActivity.objects.filter(record_id=record_id)
            .order_by("id")
            .values_list("source", flat=True)
        )
        self.assertEqual(sources, [RecordActivity.Source.MCP, RecordActivity.Source.MCP])

    async def test_soft_deleted_property_slug_can_be_reused(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        created = await self.client.post(
            f"/database/{sales_id}/property",
            json={"name": "비고", "slug": "note", "type": "text"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        deleted = await self.client.delete(
            f"/property/{created.json()['id']}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 204)
        recreated = await self.client.post(
            f"/database/{sales_id}/property",
            json={"name": "비고", "slug": "note", "type": "text"},
            headers=headers,
        )
        self.assertEqual(recreated.status_code, 201, recreated.json())
        remaining = await sync_to_async(
            Property.objects.filter(database_id=sales_id, slug="note").count
        )()
        self.assertEqual(remaining, 1)

    async def test_member_list_returns_names_for_members_only(self):
        self.user.name = "박승원"
        await sync_to_async(self.user.save)(update_fields=["name"])
        listed = await self.client.get("/", headers=self.headers())
        workspace_id = listed.json()[0]["id"]
        colleague = await sync_to_async(User.objects.create_user)(
            email="colleague@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="김영준",
        )
        await sync_to_async(WorkspaceMember.objects.create)(
            workspace_id=workspace_id,
            user=colleague,
            role=WorkspaceMember.Role.MEMBER,
        )

        response = await self.client.get(
            f"/{workspace_id}/member",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(
            response.json(),
            [
                {"user_id": self.user.id, "name": "박승원", "role": "owner"},
                {"user_id": colleague.id, "name": "김영준", "role": "member"},
            ],
        )

        denied = await self.client.get(
            f"/{workspace_id}/member",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(denied.status_code, 403)
        missing = await self.client.get("/999999/member", headers=self.headers())
        self.assertEqual(missing.status_code, 404)

    async def test_seed_is_idempotent(self):
        await sync_to_async(seed_koc_workspace)()

        @sync_to_async
        def counts():
            return (
                Workspace.objects.filter(slug="koc").count(),
                Database.objects.filter(workspace__slug="koc").count(),
                set(
                    Database.objects.filter(workspace__slug="koc").values_list(
                        "slug", flat=True
                    )
                ),
            )

        workspace_count, database_count, slugs = await counts()
        listed = await self.client.get("/", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.json()[0]["slug"], "koc")
        self.assertEqual(listed.json()[0]["role"], "owner")
        self.assertEqual(workspace_count, 1)
        self.assertEqual(database_count, 6)
        self.assertEqual(
            slugs,
            {"hr", "daily", "gov", "purchase", "sales", "docs"},
        )

    async def _database_id(self, slug: str) -> int:
        response = await self.client.get("/database", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        return next(item["id"] for item in response.json() if item["slug"] == slug)

    async def test_rich_text_block_and_invalid_annotation(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "서식 페이지",
                "icon": "file",
                "blocks": [
                    {
                        "type": "paragraph",
                        "content": {
                            "rich_text": [
                                {"text": "굵게", "annotations": {"bold": True}},
                            ]
                        },
                    }
                ],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertEqual(created.json()["icon"], "file")
        self.assertTrue(created.json()["blocks"][0]["content"]["rich_text"][0]["annotations"]["bold"])
        rejected = await self.client.post(
            f"/record/{created.json()['id']}/block",
            json={
                "type": "paragraph",
                "content": {"rich_text": [{"text": "밑줄", "annotations": {"underline": True}}]},
            },
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 400)

    async def test_board_requires_group_by(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        missing = await self.client.post(
            f"/database/{sales_id}/view",
            json={"name": "상태 보드", "type": "board"},
            headers=headers,
        )
        self.assertEqual(missing.status_code, 400)
        created = await self.client.post(
            f"/database/{sales_id}/view",
            json={"name": "상태 보드", "type": "board", "config": {"group_by": "status"}},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertEqual(created.json()["config"]["group_by"], "status")

    async def test_template_fills_record(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        template = await self.client.post(
            f"/database/{sales_id}/template",
            json={
                "name": "A/S 템플릿",
                "title": "A/S 접수",
                "values": {"status": "접수", "kind": "A/S"},
                "blocks": [{"type": "paragraph", "content": {"text": "템플릿 본문"}}],
            },
            headers=headers,
        )
        self.assertEqual(template.status_code, 201, template.json())
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={"template_id": template.json()["id"]},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertEqual(created.json()["title"], "A/S 접수")
        self.assertEqual(created.json()["values"]["status"], "접수")
        self.assertEqual(created.json()["blocks"][0]["content"]["text"], "템플릿 본문")

    async def test_trash_keeps_blocks_until_restore(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "복원 대상",
                "blocks": [{"type": "paragraph", "content": {"text": "남길 본문"}}],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        record_id = created.json()["id"]
        deleted = await self.client.delete(f"/record/{record_id}", headers=headers)
        self.assertEqual(deleted.status_code, 204)
        hidden = await self.client.get(f"/record/{record_id}", headers=headers)
        self.assertEqual(hidden.status_code, 404)
        block_count = await sync_to_async(Block.objects.filter(record_id=record_id).count)()
        self.assertEqual(block_count, 1)
        listed = await self.client.get("/", headers=headers)
        workspace_id = listed.json()[0]["id"]
        trash = await self.client.get(f"/{workspace_id}/trash", headers=headers)
        self.assertEqual(trash.status_code, 200, trash.json())
        self.assertEqual(trash.json()[0]["id"], record_id)
        restored = await self.client.post(f"/record/{record_id}/restore", headers=headers)
        self.assertEqual(restored.status_code, 200, restored.json())
        self.assertEqual(restored.json()["blocks"][0]["content"]["text"], "남길 본문")

    async def test_comment_reply_is_one_level(self):
        sales_id = await self._sales_id()
        headers = self.headers()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "댓글 대상"},
            headers=headers,
        )
        record_id = created.json()["id"]
        parent = await self.client.post(
            f"/record/{record_id}/comment",
            json={"body": "확인 부탁합니다"},
            headers=headers,
        )
        self.assertEqual(parent.status_code, 201, parent.json())
        reply = await self.client.post(
            f"/record/{record_id}/comment",
            json={"body": "확인했습니다", "parent_id": parent.json()["id"]},
            headers=headers,
        )
        self.assertEqual(reply.status_code, 201, reply.json())
        nested = await self.client.post(
            f"/record/{record_id}/comment",
            json={"body": "한 단계 더", "parent_id": reply.json()["id"]},
            headers=headers,
        )
        self.assertEqual(nested.status_code, 400)
        colleague = await sync_to_async(User.objects.create_user)(
            email="commenter@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="동료",
        )
        listed = await self.client.get("/", headers=headers)
        await sync_to_async(WorkspaceMember.objects.create)(
            workspace_id=listed.json()[0]["id"],
            user=colleague,
            role=WorkspaceMember.Role.MEMBER,
        )
        denied = await self.client.delete(
            f"/comment/{parent.json()['id']}",
            headers=self.headers(colleague),
        )
        self.assertEqual(denied.status_code, 403)

    async def test_relation_value_includes_title(self):
        headers = self.headers()
        sales_id = await self._sales_id()
        gov_id = await self._database_id("gov")
        target = await self.client.post(
            f"/database/{gov_id}/record",
            json={"title": "A사"},
            headers=headers,
        )
        self.assertEqual(target.status_code, 201, target.json())
        prop = await self.client.post(
            f"/database/{sales_id}/property",
            json={
                "name": "거래처",
                "slug": "client",
                "type": "relation",
                "config": {"database_id": gov_id},
            },
            headers=headers,
        )
        self.assertEqual(prop.status_code, 201, prop.json())
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "견적", "values": {"client": [target.json()["id"]]}},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertEqual(
            created.json()["values"]["client"],
            [
                {
                    "id": target.json()["id"],
                    "title": "A사",
                    "database_id": gov_id,
                    "database_slug": "gov",
                }
            ],
        )
