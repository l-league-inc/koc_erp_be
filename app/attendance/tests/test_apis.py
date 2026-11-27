from datetime import datetime
from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.errors import HttpError
from ninja.testing import TestAsyncClient

from attendance.api import router
from notification.models import Notification
from user.utils import get_access_token
from workspace.models import Database, Property, Record, RecordActivity, Workspace, WorkspaceMember
from workspace.seed import seed_koc_workspace
from workspace.utils import create_record, delete_record, export_values, update_record

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

    def headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    def _member(self):
        user = User.objects.create_user(
            email="member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="이멤버",
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=user,
            role=WorkspaceMember.Role.MEMBER,
        )
        return user

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

    async def test_member_cannot_rewrite_clock_times_or_approved_overtime(self):
        member = await sync_to_async(self._member)()
        person = await sync_to_async(self._person)("이멤버", member.email)
        with patch("attendance.service.timezone.now", return_value=MORNING):
            clocked = await self.client.post(
                "/clock-in",
                json={"workspace_id": self.workspace.id},
                headers=self.headers(member),
            )
            self.assertEqual(clocked.status_code, 200, clocked.json())
            record_id = clocked.json()["record_id"]
            self.assertIsNone(clocked.json()["overtime_minutes"])
            self.assertIsNone(clocked.json()["overtime_status"])

            requested = await self.client.post(
                "/overtime",
                json={"workspace_id": self.workspace.id, "minutes": 90, "reason": "납품"},
                headers=self.headers(member),
            )
            forbidden = await self.client.post(
                "/overtime/decide",
                json={
                    "workspace_id": self.workspace.id,
                    "record_id": record_id,
                    "decision": "승인",
                },
                headers=self.headers(member),
            )
            approved = await self.client.post(
                "/overtime/decide",
                json={
                    "workspace_id": self.workspace.id,
                    "record_id": record_id,
                    "decision": "승인",
                },
                headers=self.headers(),
            )
            again = await self.client.post(
                "/overtime",
                json={"workspace_id": self.workspace.id, "minutes": 30, "reason": "추가"},
                headers=self.headers(member),
            )
        with self.assertRaises(HttpError) as denied:
            await sync_to_async(update_record)(
                member,
                record_id,
                {"values": {"check_out": "2026-11-26T22:00:00"}},
                RecordActivity.Source.USER,
            )
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(denied.exception.message, "출근·퇴근 시각은 직접 수정할 수 없습니다.")

        await sync_to_async(update_record)(
            member,
            record_id,
            {"values": {"check_in": "2026-11-26T09:01:02"}},
            RecordActivity.Source.USER,
        )
        with self.assertRaises(HttpError) as agent_denied:
            await sync_to_async(update_record)(
                self.user,
                record_id,
                {"values": {"check_out": "2026-11-26T22:00:00"}},
                RecordActivity.Source.AGENT,
            )
        self.assertEqual(agent_denied.exception.status_code, 403)

        corrected = await sync_to_async(update_record)(
            self.user,
            record_id,
            {"values": {"check_out": "2026-11-26T19:00:00"}},
            RecordActivity.Source.USER,
        )
        self.assertTrue(str(corrected["values"]["check_out"]).startswith("2026-11-26T19:00:00"))

        self.assertEqual(requested.status_code, 200, requested.json())
        self.assertEqual(requested.json()["overtime_minutes"], 90)
        self.assertEqual(requested.json()["overtime_reason"], "납품")
        self.assertEqual(requested.json()["overtime_status"], "대기")
        self.assertEqual(requested.json()["employee_id"], person["id"])
        note = await Notification.objects.filter(user=self.user, metadata__kind="overtime").afirst()
        self.assertIsNotNone(note)
        self.assertEqual(note.metadata["record_id"], record_id)
        self.assertIn("90분", note.message)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["detail"], "관리자만 야근을 승인할 수 있습니다.")
        self.assertEqual(approved.status_code, 200, approved.json())
        self.assertEqual(approved.json()["overtime_status"], "승인")
        self.assertEqual(approved.json()["overtime_minutes"], 90)
        self.assertEqual(again.status_code, 403)
        self.assertEqual(again.json()["detail"], "승인된 야근 시간은 수정할 수 없습니다.")

        with self.assertRaises(HttpError) as locked:
            await sync_to_async(delete_record)(member, record_id)
        self.assertEqual(locked.exception.status_code, 403)
        self.assertEqual(locked.exception.message, "근무 기록은 직접 삭제할 수 없습니다.")

    async def test_overtime_requires_clock_in_and_rejects_other_people(self):
        member = await sync_to_async(self._member)()
        await sync_to_async(self._person)("이멤버", member.email)
        missing = await self.client.post(
            "/overtime",
            json={"workspace_id": self.workspace.id, "minutes": 30, "reason": ""},
            headers=self.headers(member),
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], "출근 기록이 없습니다.")

        other = await sync_to_async(self._person)("다른사람", "other@example.com")
        foreign = await sync_to_async(create_record)(
            self.user,
            self.attendance.id,
            {
                "title": "2026-11-26 출근",
                "values": {
                    "work_date": "2026-11-26",
                    "employee": [other["id"]],
                    "check_in": "2026-11-26T09:00:00",
                },
            },
            RecordActivity.Source.USER,
        )
        with self.assertRaises(HttpError) as denied:
            await sync_to_async(update_record)(
                member,
                foreign["id"],
                {"values": {"overtime_minutes": 60, "overtime_reason": "대신"}},
                RecordActivity.Source.USER,
            )
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(denied.exception.message, "본인 근무 기록에만 야근을 신청할 수 있습니다.")

        with self.assertRaises(HttpError) as past:
            await sync_to_async(create_record)(
                member,
                self.attendance.id,
                {
                    "title": "2020-01-01 출근",
                    "values": {"work_date": "2020-01-01", "employee": [other["id"]]},
                },
                RecordActivity.Source.USER,
            )
        self.assertEqual(past.exception.status_code, 403)
        self.assertEqual(past.exception.message, "근무일과 임직원은 본인 오늘 기록만 만들 수 있습니다.")
