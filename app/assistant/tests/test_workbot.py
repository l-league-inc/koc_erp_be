from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from ninja.testing import TestAsyncClient

from assistant.api import workbot_router
from assistant.models import Workbot, WorkbotRun
from notification.models import Notification
from user.utils import get_access_token
from workspace.models import Database, Record
from workspace.seed import seed_koc_workspace
from workspace.utils import create_record

User = get_user_model()


class WorkbotApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(workbot_router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )
        seed_koc_workspace()
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )

    def headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token({"user_id": user.id, "env": settings.DJANGO_ENV_NAME})
        return {"Authorization": f"Bearer {token}"}

    async def _workspace_id(self) -> int:
        from workspace.api import router as workspace_router

        client = TestAsyncClient(workspace_router)
        listed = await client.get("/", headers=self.headers())
        return listed.json()[0]["id"]

    def _notify_spec(self, *, confirm: bool = False) -> dict:
        return {
            "filters": [{"property": "status", "op": "eq", "value": "대기"}],
            "action": "notify",
            "notify_user_ids": [self.user.id],
            "message": "미작성 업무가 있습니다",
            "requires_confirmation": confirm,
        }

    async def _create_waiting_record(self):
        database = await sync_to_async(Database.objects.get)(slug="hr", workspace__slug="koc")
        await sync_to_async(create_record)(
            self.user,
            database.id,
            {"title": "미작성", "values": {"status": "대기"}},
            "user",
        )

    async def test_notify_run_creates_notification_and_stats(self):
        await self._create_waiting_record()
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/",
            json={
                "workspace_id": workspace_id,
                "name": "근태 마감 알림봇",
                "description": "미입력 알림",
                "instruction": "대기 건을 알려줘",
                "database_slug": "hr",
                "schedule": "30 9 * * *",
                "estimated_minutes": 10,
                "spec": self._notify_spec(),
            },
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        self.assertIsNotNone(created.json()["next_run_at"])
        bot_id = created.json()["id"]

        ran = await self.client.post(f"/{bot_id}/run", headers=self.headers())
        self.assertEqual(ran.status_code, 200, ran.json())
        self.assertEqual(ran.json()["status"], "success")
        self.assertIn("1건", ran.json()["summary"])

        note = await sync_to_async(Notification.objects.get)(user=self.user)
        self.assertEqual(note.metadata["workbot_id"], bot_id)
        self.assertEqual(note.metadata["run_id"], ran.json()["id"])

        stats = await self.client.get("/stats", headers=self.headers())
        self.assertEqual(stats.status_code, 200, stats.json())
        self.assertEqual(stats.json()["active_count"], 1)
        self.assertEqual(stats.json()["month_run_count"], 1)
        self.assertEqual(stats.json()["success_rate"], 100.0)
        self.assertEqual(stats.json()["saved_minutes"], 10)

        denied = await self.client.get("/", headers=self.headers(self.outsider))
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(denied.json(), [])

    async def test_waiting_run_confirms_before_notification(self):
        await self._create_waiting_record()
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/",
            json={
                "workspace_id": workspace_id,
                "name": "확인 봇",
                "database_slug": "hr",
                "schedule": "* * * * *",
                "spec": self._notify_spec(confirm=True),
            },
            headers=self.headers(),
        )
        bot_id = created.json()["id"]
        ran = await self.client.post(f"/{bot_id}/run", headers=self.headers())
        self.assertEqual(ran.json()["status"], "waiting")
        self.assertEqual(await sync_to_async(Notification.objects.count)(), 0)

        confirmed = await self.client.post(
            f"/run/{ran.json()['id']}/confirm",
            headers=self.headers(),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.json())
        self.assertEqual(confirmed.json()["status"], "success")
        self.assertEqual(await sync_to_async(Notification.objects.count)(), 1)

    async def test_create_record_action_and_delete(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/",
            json={
                "workspace_id": workspace_id,
                "name": "발주 봇",
                "database_slug": "hr",
                "schedule": "0 18 * * *",
                "spec": {
                    "action": "create_record",
                    "filters": [],
                    "record": {"title": "발주 추천", "values": {"status": "대기"}},
                },
            },
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        ran = await self.client.post(f"/{created.json()['id']}/run", headers=self.headers())
        self.assertEqual(ran.json()["status"], "success", ran.json())
        self.assertEqual(await sync_to_async(Record.objects.filter(title="발주 추천").count)(), 1)

        deleted = await self.client.delete(f"/{created.json()['id']}", headers=self.headers())
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(await sync_to_async(Workbot.objects.count)(), 0)

    async def test_draft_does_not_save(self):
        workspace_id = await self._workspace_id()

        def fake_json(messages):
            return {
                "name": "근태 마감 알림봇",
                "description": "미입력 알림",
                "database_slug": "hr",
                "schedule": "30 9 * * 5",
                "estimated_minutes": 5,
                "spec": self._notify_spec(),
            }

        with patch("assistant.workbot.llm.complete_json", fake_json):
            drafted = await self.client.post(
                "/draft",
                json={"workspace_id": workspace_id, "instruction": "매주 금요일 미작성 업무를 알려줘"},
                headers=self.headers(),
            )
        self.assertEqual(drafted.status_code, 200, drafted.json())
        self.assertEqual(drafted.json()["schedule"], "30 9 * * 5")
        self.assertEqual(await sync_to_async(Workbot.objects.count)(), 0)

    async def test_command_runs_due_bot_only(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/",
            json={
                "workspace_id": workspace_id,
                "name": "일정 봇",
                "database_slug": "hr",
                "schedule": "* * * * *",
                "enabled": True,
                "spec": self._notify_spec(),
            },
            headers=self.headers(),
        )
        bot = await sync_to_async(Workbot.objects.get)(id=created.json()["id"])
        bot.next_run_at = timezone.now() - timedelta(minutes=2)
        await sync_to_async(bot.save)(update_fields=["next_run_at"])
        await sync_to_async(call_command)("run_due_workbots")
        await sync_to_async(bot.refresh_from_db)()
        self.assertEqual(await sync_to_async(WorkbotRun.objects.count)(), 1)
        self.assertGreater(bot.next_run_at, timezone.now() - timedelta(seconds=1))

        bot.enabled = False
        bot.next_run_at = timezone.now() - timedelta(minutes=2)
        await sync_to_async(bot.save)(update_fields=["enabled", "next_run_at"])
        await sync_to_async(call_command)("run_due_workbots")
        self.assertEqual(await sync_to_async(WorkbotRun.objects.count)(), 1)
