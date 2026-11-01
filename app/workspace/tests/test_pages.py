from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from user.utils import get_access_token
from workspace.api import router
from workspace.models import Database, Record
from workspace.pages import seed_koc_pages
from workspace.utils import export_values

User = get_user_model()


class KocPageSeedTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.result = seed_koc_pages()

    def headers(self):
        token, _expires = get_access_token(
            {"user_id": self.user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    def test_csv_pages_are_idempotent(self):
        self.assertEqual(self.result["warnings"], [])
        self.assertEqual(self.result["database_count"], 13)
        self.assertEqual(self.result["created_count"], 123)
        self.assertEqual(self.result["record_count"], 123)
        self.assertEqual(
            set(Database.objects.filter(section_slug="hr").values_list("slug", flat=True)),
            {"employees", "attendance", "leave", "trip"},
        )
        self.assertFalse(Database.objects.filter(name="통합관리대장").exists())

        again = seed_koc_pages()
        self.assertEqual(again["created_count"], 0)
        self.assertEqual(again["record_count"], 123)
        self.assertEqual(again["warnings"], [])

    def test_imported_values_and_relations(self):
        employee = Record.objects.get(database__slug="employees", title="조인아")
        employee_values = export_values(employee)
        self.assertEqual(employee_values["employee_no"], "EMP-3")
        self.assertEqual(employee_values["employment_status"], "재직")
        self.assertTrue(employee_values["hired_on"].startswith("2025-10-01"))

        attendance = Record.objects.get(database__slug="attendance", title="2026년 10월 12일 출근")
        self.assertEqual(export_values(attendance)["employee"][0]["title"], "박승원")

        expense = Record.objects.get(title="[전남형] MOU 협약식 회의비")
        expense_values = export_values(expense)
        self.assertEqual(expense_values["project"][0]["title"], "전남형 청년창업사관학교")
        self.assertEqual(expense_values["total"], "295500")

        quote = Record.objects.get(database__slug="quotes", title__contains="(Q01)")
        self.assertEqual(export_values(quote)["client"][0]["title"], "LG U+ 레저파워")
        self.assertEqual(export_values(quote)["total"], "59400")

        trip = Record.objects.get(database__slug="trip")
        period = export_values(trip)["period"]
        self.assertTrue(period["start"].startswith("2026-10-27"))
        self.assertTrue(period["end"].startswith("2026-10-28"))

        task = Record.objects.get(title="전남청년창업사관학교 미팅")
        self.assertTrue(export_values(task)["done"])
        self.assertEqual(export_values(Record.objects.get(title="인버터"))["quantity"], "28")

    async def test_section_is_in_database_response(self):
        listed = await self.client.get("/database", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.content)
        employees = next(item for item in listed.json() if item["slug"] == "employees")
        self.assertEqual(employees["section"], "인사 / 근태 관리")
        self.assertEqual(employees["section_slug"], "hr")

        created = await self.client.post(
            "/database",
            json={
                "workspace_id": self.result["workspace"].id,
                "name": "임시",
                "slug": "temp_section",
                "section": "영업 / 견적 / A/S",
                "section_slug": "sales",
            },
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["section_slug"], "sales")
        self.assertTrue(
            await sync_to_async(Database.objects.filter(slug="temp_section").exists)()
        )
