from datetime import datetime
from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from attendance.api import router
from user.utils import get_access_token
from workspace.models import Database, Property, Record, RecordActivity, Workspace
from workspace.seed import seed_koc_workspace
from workspace.utils import create_record, export_values

User = get_user_model()

MORNING = datetime(2026, 11, 26, 9, 1, 2)
EVENING = datetime(2026, 11, 26, 18, 5, 0)


class AttendanceApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="worker@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="김근무",
        )
        seed_koc_workspace()
        self.workspace = Workspace.objects.get(slug="koc")
        self.employees, self.attendance = self._tables()

    def headers(self):
        token, _expires = get_access_token(
            {"user_id": self.user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    def _tables(self) -> tuple[Database, Database]:
        employees = Database.objects.create(
            workspace=self.workspace, name="임직원", slug="employees"
        )
        Property.objects.create(
            database=employees, name="이름", slug="title", type=Property.Type.TITLE
        )
        Property.objects.create(
            database=employees, name="사내 이메일", slug="email", type=Property.Type.EMAIL
        )
        attendance = Database.objects.create(
            workspace=self.workspace, name="근무 기록", slug="attendance"
        )
        Property.objects.create(
            database=attendance, name="근무기록명", slug="title", type=Property.Type.TITLE
        )
        Property.objects.create(
            database=attendance, name="근무일", slug="work_date", type=Property.Type.DATE
        )
        Property.objects.create(
            database=attendance, name="출근시각", slug="check_in", type=Property.Type.DATE
        )
        Property.objects.create(
            database=attendance, name="퇴근시각", slug="check_out", type=Property.Type.DATE
        )
        Property.objects.create(
            database=attendance,
            name="등록시각(자동)",
            slug="registered_at",
            type=Property.Type.DATE,
        )
        Property.objects.create(
            database=attendance,
            name="임직원",
            slug="employee",
            type=Property.Type.RELATION,
            config={"database_id": employees.id},
        )
        return employees, attendance

    def _person(self, title: str, email: str) -> dict:
        return create_record(
            self.user,
            self.employees.id,
            {"title": title, "values": {"email": email}},
            RecordActivity.Source.USER,
        )

    async def test_clock_in_stamps_now_and_blocks_a_second_clock_in(self):
        person = await sync_to_async(self._person)("김근무", self.user.email)
        with patch("attendance.service.timezone.now", return_value=MORNING):
            empty = await self.client.get(
                f"/today?workspace_id={self.workspace.id}",
                headers=self.headers(),
            )
            clocked = await self.client.post(
                "/clock-in",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
            again = await self.client.post(
                "/clock-in",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
        self.assertEqual(empty.status_code, 200, empty.json())
        self.assertEqual(empty.json()["state"], "none")
        self.assertIsNone(empty.json()["record_id"])
        self.assertIsNone(empty.json()["check_in"])
        self.assertEqual(clocked.status_code, 200, clocked.json())
        body = clocked.json()
        self.assertEqual(body["state"], "in")
        self.assertEqual(body["work_date"], "2026-11-26")
        self.assertEqual(body["check_in"], "2026-11-26T09:01:02")
        self.assertIsNone(body["check_out"])
        self.assertEqual(body["title"], "2026-11-26 출근")
        self.assertEqual(body["employee_id"], person["id"])
        self.assertEqual(body["employee_title"], "김근무")
        record = await Record.objects.aget(id=body["record_id"])
        values = await sync_to_async(export_values)(record)
        self.assertTrue(str(values["registered_at"]).startswith("2026-11-26T09:01:02"))
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"], "오늘 출근은 이미 있습니다.")
        self.assertEqual(
            await Record.objects.filter(database_id=self.attendance.id).acount(),
            1,
        )

    async def test_clock_in_fills_an_empty_check_in_on_todays_row(self):
        person = await sync_to_async(self._person)("다른이름", self.user.email)
        existing = await sync_to_async(create_record)(
            self.user,
            self.attendance.id,
            {
                "title": "2026-11-26 출근",
                "values": {"work_date": "2026-11-26", "employee": [person["id"]]},
            },
            RecordActivity.Source.USER,
        )
        with patch("attendance.service.timezone.now", return_value=MORNING):
            clocked = await self.client.post(
                "/clock-in",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
        self.assertEqual(clocked.status_code, 200, clocked.json())
        self.assertEqual(clocked.json()["record_id"], existing["id"])
        self.assertEqual(clocked.json()["check_in"], "2026-11-26T09:01:02")
        self.assertEqual(clocked.json()["state"], "in")
        self.assertEqual(
            await Record.objects.filter(database_id=self.attendance.id).acount(),
            1,
        )

    async def test_clock_out_stamps_now_after_clock_in(self):
        await sync_to_async(self._person)("김근무", self.user.email)
        with patch("attendance.service.timezone.now", return_value=MORNING):
            missing = await self.client.post(
                "/clock-out",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
            await self.client.post(
                "/clock-in",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], "출근 기록이 없습니다.")
        with patch("attendance.service.timezone.now", return_value=EVENING):
            clocked = await self.client.post(
                "/clock-out",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
            again = await self.client.post(
                "/clock-out",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(),
            )
            today = await self.client.get(
                f"/today?workspace_id={self.workspace.id}",
                headers=self.headers(),
            )
        self.assertEqual(clocked.status_code, 200, clocked.json())
        self.assertEqual(clocked.json()["state"], "out")
        self.assertEqual(clocked.json()["check_in"], "2026-11-26T09:01:02")
        self.assertEqual(clocked.json()["check_out"], "2026-11-26T18:05:00")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"], "오늘 퇴근은 이미 있습니다.")
        self.assertEqual(today.status_code, 200, today.json())
        self.assertEqual(today.json()["state"], "out")

    async def test_missing_employee_and_ambiguous_name_are_rejected(self):
        missing = await self.client.post(
            "/clock-in",
            json={"workspace_id": self.workspace.id},
            headers=self.headers(),
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], "임직원 기록이 없습니다.")
        await sync_to_async(self._person)("김근무", "one@example.com")
        await sync_to_async(self._person)("김근무", "two@example.com")
        ambiguous = await self.client.post(
            "/clock-in",
            json={"workspace_id": self.workspace.id},
            headers=self.headers(),
        )
        self.assertEqual(ambiguous.status_code, 400)
        self.assertEqual(ambiguous.json()["detail"], "임직원 기록이 여러 건입니다.")

    async def test_missing_attendance_database_is_rejected(self):
        await sync_to_async(self.attendance.delete)()
        response = await self.client.get(
            f"/today?workspace_id={self.workspace.id}",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "근무 기록 데이터베이스가 없습니다.")
