from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import Database, Property, RecordActivity, Workspace
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
