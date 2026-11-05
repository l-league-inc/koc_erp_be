from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import Page, Property, RelationLink
from workspace.seed import seed_koc_workspace

User = get_user_model()


class NotionWorkspaceTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = seed_koc_workspace()
        self.headers = self._headers()

    def _headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def _sales_id(self) -> int:
        response = await self.client.get("/database", headers=self.headers)
        sales = next(item for item in response.json() if item["slug"] == "sales")
        return sales["id"]

    async def test_seed_creates_database_pages(self):
        response = await self.client.get(
            f"/{self.workspace.id}/page",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.json())
        kinds = {item["kind"] for item in response.json()}
        self.assertIn("database", kinds)
        sales = next(item for item in response.json() if item["name"] == "영업 / 견적 / A/S")
        self.assertEqual(sales["kind"], "database")
        self.assertIsNone(sales["parent_id"])

    async def test_document_page_blocks_and_duplicate(self):
        created = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "회의록"},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        page_id = created.json()["id"]
        block = await self.client.post(
            f"/page/{page_id}/block",
            json={"type": "paragraph", "content": {"text": "안건"}},
            headers=self.headers,
        )
        self.assertEqual(block.status_code, 201, block.json())
        self.assertIsNone(block.json()["record_id"])
        self.assertEqual(block.json()["page_id"], page_id)

        copied = await self.client.post(
            f"/page/{page_id}/duplicate",
            headers=self.headers,
        )
        self.assertEqual(copied.status_code, 201, copied.json())
        self.assertEqual(copied.json()["name"], "회의록 복사")
        self.assertEqual(copied.json()["blocks"][0]["content"]["text"], "안건")

        deleted = await self.client.delete(f"/page/{page_id}", headers=self.headers)
        self.assertEqual(deleted.status_code, 204)
        trash = await self.client.get(f"/{self.workspace.id}/trash", headers=self.headers)
        self.assertTrue(any(item["kind"] == "page" and item["id"] == page_id for item in trash.json()))
        restored = await self.client.post(f"/page/{page_id}/restore", headers=self.headers)
        self.assertEqual(restored.status_code, 200, restored.json())

    async def test_move_rejects_cycle_and_updates_section(self):
        folder = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "folder", "name": "영업", "slug": "sales_folder"},
            headers=self.headers,
        )
        self.assertEqual(folder.status_code, 201, folder.json())
        folder_id = folder.json()["id"]
        child = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "folder", "name": "하위", "slug": "sales_child", "parent_id": folder_id},
            headers=self.headers,
        )
        moved = await self.client.post(
            f"/page/{folder_id}/move",
            json={"parent_id": child.json()["id"], "position": 0},
            headers=self.headers,
        )
        self.assertEqual(moved.status_code, 400)

        sales_page = await sync_to_async(
            Page.objects.select_related("database").get
        )(database__slug="sales", kind=Page.Kind.DATABASE)
        placed = await self.client.post(
            f"/page/{sales_page.id}/move",
            json={"parent_id": folder_id, "position": 1},
            headers=self.headers,
        )
        self.assertEqual(placed.status_code, 200, placed.json())
        await sync_to_async(sales_page.database.refresh_from_db)()
        self.assertEqual(sales_page.database.section, "영업")
        self.assertEqual(sales_page.database.section_slug, "sales_folder")

    async def test_query_finds_block_text_and_system_field(self):
        sales_id = await self._sales_id()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "표제",
                "values": {"status": "접수", "kind": "A/S"},
                "blocks": [{"type": "paragraph", "content": {"text": "숨은본문"}}],
            },
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        queried = await self.client.post(
            "/query",
            json={"database_slug": "sales", "q": "숨은본문"},
            headers=self.headers,
        )
        self.assertEqual(queried.status_code, 200, queried.json())
        self.assertEqual(queried.json()["data"][0]["title"], "표제")

        by_author = await self.client.post(
            "/query",
            json={
                "database_slug": "sales",
                "filters": [{"property": "created_by", "op": "eq", "value": "me"}],
                "sorts": [{"property": "created_at", "direction": "desc"}],
            },
            headers=self.headers,
        )
        self.assertEqual(by_author.status_code, 200, by_author.json())
        self.assertEqual(by_author.json()["data"][0]["title"], "표제")

        grouped = await self.client.post(
            "/query",
            json={
                "database_slug": "sales",
                "filters": {
                    "op": "or",
                    "filters": [
                        {"property": "status", "op": "eq", "value": "접수"},
                        {"property": "status", "op": "eq", "value": "완료"},
                    ],
                },
            },
            headers=self.headers,
        )
        self.assertEqual(grouped.status_code, 200, grouped.json())
        self.assertEqual(grouped.json()["data"][0]["title"], "표제")

    async def test_search_returns_document_and_record(self):
        await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "검색문서"},
            headers=self.headers,
        )
        sales_id = await self._sales_id()
        await self.client.post(
            f"/database/{sales_id}/record",
            json={"title": "검색행"},
            headers=self.headers,
        )
        found = await self.client.post(
            "/search",
            json={"workspace_id": self.workspace.id, "q": "검색"},
            headers=self.headers,
        )
        self.assertEqual(found.status_code, 200, found.json())
        kinds = {item["kind"] for item in found.json()["data"]}
        self.assertEqual(kinds, {"page", "record"})

    async def test_two_way_relation_and_duplicate(self):
        sales_id = await self._sales_id()
        clients = await self.client.post(
            "/database",
            json={
                "workspace_id": self.workspace.id,
                "name": "거래처",
                "slug": "clients_extra",
            },
            headers=self.headers,
        )
        self.assertEqual(clients.status_code, 201, clients.json())
        client_db = clients.json()["id"]
        relation = await self.client.post(
            f"/database/{sales_id}/property",
            json={
                "name": "거래처",
                "slug": "client",
                "type": "relation",
                "config": {"database_id": client_db, "two_way": True},
            },
            headers=self.headers,
        )
        self.assertEqual(relation.status_code, 201, relation.json())
        self.assertTrue(relation.json()["config"]["two_way"])
        reverse_id = relation.json()["config"]["synced_property_id"]
        reverse = await sync_to_async(Property.objects.get)(id=reverse_id)
        self.assertEqual(reverse.database_id, client_db)
        self.assertEqual(reverse.config["synced_property_id"], relation.json()["id"])

        client = await self.client.post(
            f"/database/{client_db}/record",
            json={"title": "A사"},
            headers=self.headers,
        )
        deal = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "견적",
                "values": {
                    "status": "접수",
                    "kind": "견적",
                    "client": [client.json()["id"]],
                },
            },
            headers=self.headers,
        )
        self.assertEqual(deal.status_code, 201, deal.json())
        links = await sync_to_async(RelationLink.objects.filter(to_record_id=deal.json()["id"]).count)()
        self.assertEqual(links, 1)

        copied = await self.client.post(
            f"/record/{deal.json()['id']}/duplicate",
            headers=self.headers,
        )
        self.assertEqual(copied.status_code, 201, copied.json())
        self.assertEqual(copied.json()["title"], "견적 복사")
        self.assertEqual(copied.json()["values"]["client"][0]["id"], client.json()["id"])

    async def test_view_hides_columns_and_favorite(self):
        sales_id = await self._sales_id()
        view = await self.client.post(
            f"/database/{sales_id}/view",
            json={
                "name": "좁은 표",
                "type": "table",
                "config": {
                    "hidden_properties": ["amount"],
                    "column_widths": {"status": 120},
                    "group_by": "status",
                },
            },
            headers=self.headers,
        )
        self.assertEqual(view.status_code, 201, view.json())
        hidden_title = await self.client.post(
            f"/database/{sales_id}/view",
            json={
                "name": "제목 숨김",
                "type": "table",
                "config": {"hidden_properties": ["title"]},
            },
            headers=self.headers,
        )
        self.assertEqual(hidden_title.status_code, 400)

        page = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "즐겨찾기"},
            headers=self.headers,
        )
        favorite = await self.client.post(
            f"/page/{page.json()['id']}/favorite",
            headers=self.headers,
        )
        self.assertEqual(favorite.status_code, 201, favorite.json())
        listed = await self.client.get(
            f"/{self.workspace.id}/favorite",
            headers=self.headers,
        )
        self.assertEqual(listed.json()[0]["page_id"], page.json()["id"])

    async def test_appflowy_blocks_formula_and_page_mention(self):
        page = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": "회의록"},
            headers=self.headers,
        )
        self.assertEqual(page.status_code, 201, page.json())
        page_id = page.json()["id"]
        sales_id = await self._sales_id()
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "서식 본문",
                "blocks": [
                    {
                        "type": "simple_table",
                        "content": {
                            "column_widths": {"0": 160},
                            "enable_header_row": True,
                            "column_aligns": {"0": "Left"},
                        },
                        "children": [
                            {
                                "type": "simple_table_row",
                                "children": [
                                    {
                                        "type": "simple_table_cell",
                                        "children": [
                                            {
                                                "type": "paragraph",
                                                "content": {
                                                    "rich_text": [
                                                        {"formula": "E=mc^2"},
                                                        {
                                                            "text": "회의록",
                                                            "mention": {
                                                                "type": "page",
                                                                "page_id": page_id,
                                                            },
                                                        },
                                                    ]
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {"type": "math_equation", "content": {"formula": "a^2+b^2=c^2"}},
                    {
                        "type": "link_preview",
                        "content": {"url": "https://example.com", "title": "예시"},
                    },
                    {
                        "type": "simple_columns",
                        "children": [
                            {
                                "type": "simple_column",
                                "content": {"ratio": 0.5},
                                "children": [
                                    {"type": "paragraph", "content": {"text": "왼쪽"}}
                                ],
                            }
                        ],
                    },
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        types = {item["type"] for item in created.json()["blocks"]}
        self.assertEqual(
            types,
            {
                "simple_table",
                "simple_table_row",
                "simple_table_cell",
                "paragraph",
                "math_equation",
                "link_preview",
                "simple_columns",
                "simple_column",
            },
        )
        record_id = created.json()["id"]
        rejected = await self.client.post(
            f"/record/{record_id}/block",
            json={"type": "simple_table_row", "content": {}},
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 400)
        missing_page = await self.client.post(
            f"/record/{record_id}/block",
            json={
                "type": "paragraph",
                "content": {
                    "rich_text": [
                        {"text": "없는 페이지", "mention": {"type": "page", "page_id": 999999}}
                    ]
                },
            },
            headers=self.headers,
        )
        self.assertEqual(missing_page.status_code, 400)
        bad_url = await self.client.post(
            f"/record/{record_id}/block",
            json={"type": "link_preview", "content": {"url": "ftp://example.com"}},
            headers=self.headers,
        )
        self.assertEqual(bad_url.status_code, 400)
