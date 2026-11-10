from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from assistant import scheduler
from assistant.models import Workbot, WorkbotRun
from assistant.workbot import claim_due_workbots, confirm_run, run_due_workbots
from notification.models import Notification
from workspace.models import Block, Record, Workspace
from workspace.seed import seed_koc_workspace

User = get_user_model()


class WorkbotSchedulerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )
        seed_koc_workspace()
        self.workspace = Workspace.objects.get(slug="koc")

    def _bot(self, spec: dict, **extra) -> Workbot:
        defaults = {
            "workspace": self.workspace,
            "owner": self.user,
            "name": "주간 보고 봇",
            "instruction": "매주 월요일 지난주 근태를 정리한 보고서 페이지를 만들어줘",
            "spec": spec,
            "schedule": "0 9 * * 1",
            "enabled": True,
            "database_slug": "hr",
            "next_run_at": timezone.now() - timedelta(minutes=3),
        }
        defaults.update(extra)
        return Workbot.objects.create(**defaults)

    def _agent_spec(self, **extra) -> dict:
        return {
            "action": "agent",
            "filters": [],
            "notify_user_ids": [],
            "message": "주간 보고서",
            "requires_confirmation": False,
            "record": None,
            **extra,
        }

    @staticmethod
    def _fake_llm(title: str):
        calls = {"n": 0}

        def fake(messages, tools, model=""):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "create_record",
                            "arguments": {
                                "database_slug": "hr",
                                "title": title,
                                "values": {},
                                "blocks": [
                                    {"type": "heading_2", "content": {"text": "요약"}},
                                    {"type": "paragraph", "content": {"text": "이번 주 근태 이상 없음"}},
                                ],
                            },
                        }
                    ],
                }
            return {"content": "주간 보고서를 만들었습니다.", "tool_calls": []}

        return fake

    def test_claim_is_exclusive(self):
        bot = self._bot(self._agent_spec())
        now = timezone.now()
        first = claim_due_workbots(now)
        second = claim_due_workbots(now)
        self.assertEqual([item.id for item in first], [bot.id])
        self.assertEqual(second, [])
        bot.refresh_from_db()
        self.assertGreater(bot.next_run_at, now)

    def test_claim_fills_missing_next_run(self):
        bot = self._bot(self._agent_spec(), next_run_at=None, schedule="* * * * *")
        claim_due_workbots(timezone.now())
        bot.refresh_from_db()
        self.assertIsNotNone(bot.next_run_at)

    def test_due_agent_bot_writes_page_with_body_and_notifies(self):
        bot = self._bot(self._agent_spec())
        with patch("assistant.workbot_agent.llm.complete", self._fake_llm("주간 보고 11월 2주")):
            self.assertEqual(run_due_workbots(), 1)
        run = WorkbotRun.objects.get(workbot=bot)
        self.assertEqual(run.status, WorkbotRun.Status.SUCCESS, run.summary)
        record = Record.objects.get(title="주간 보고 11월 2주")
        self.assertEqual(run.record_ids, [record.id])
        self.assertEqual(Block.objects.filter(record=record).count(), 2)
        note = Notification.objects.get(user=self.user)
        self.assertEqual(note.metadata["workbot_id"], bot.id)
        self.assertIn("주간 보고서", note.message)
        bot.refresh_from_db()
        self.assertIsNotNone(bot.last_run_at)

    def test_agent_waits_for_confirmation_then_applies(self):
        bot = self._bot(self._agent_spec(requires_confirmation=True))
        with patch("assistant.workbot_agent.llm.complete", self._fake_llm("확인 후 보고서")):
            run_due_workbots()
        run = WorkbotRun.objects.get(workbot=bot)
        self.assertEqual(run.status, WorkbotRun.Status.WAITING)
        self.assertFalse(Record.objects.filter(title="확인 후 보고서").exists())
        self.assertEqual(Notification.objects.count(), 0)

        confirm_run(self.user, run.id)
        record = Record.objects.get(title="확인 후 보고서")
        self.assertEqual(Block.objects.filter(record=record).count(), 2)
        self.assertEqual(Notification.objects.count(), 1)

    def test_scheduled_failure_notifies_owner(self):
        bot = self._bot(self._agent_spec())
        with patch("assistant.workbot_agent.llm.complete", side_effect=RuntimeError("boom")):
            run_due_workbots()
        run = WorkbotRun.objects.get(workbot=bot)
        self.assertEqual(run.status, WorkbotRun.Status.FAILED)
        note = Notification.objects.get(user=self.user)
        self.assertIn("실행 실패", note.message)

    def test_create_record_spec_keeps_blocks(self):
        bot = self._bot(
            {
                "action": "create_record",
                "filters": [],
                "record": {
                    "title": "고정 문서",
                    "values": {},
                    "blocks": [{"type": "paragraph", "content": {"text": "본문"}}],
                },
            }
        )
        run_due_workbots()
        run = WorkbotRun.objects.get(workbot=bot)
        self.assertEqual(run.status, WorkbotRun.Status.SUCCESS, run.summary)
        self.assertEqual(Block.objects.filter(record__title="고정 문서").count(), 1)

    @override_settings(WORKBOT_SCHEDULER_ENABLED=False)
    def test_scheduler_off_by_setting(self):
        self.assertFalse(scheduler.start_scheduler())


class WorkbotDateValueTests(WorkbotSchedulerTests):
    def _run_with_date(self, value):
        bot = self._bot(
            {
                "action": "create_record",
                "filters": [],
                "record": {"title": "날짜 문서", "values": {"due_date": value}},
            }
        )
        run_due_workbots()
        return WorkbotRun.objects.get(workbot=bot)

    def test_accepts_common_date_formats(self):
        for value in (
            "2026.11.09",
            "2026/11/09",
            "2026년 11월 9일",
            "2026년 11월 9일 오후 3:00 (GMT+9)",
            "2026-11-09 ~ 2026-11-15",
            {"start": "2026년 11월 9일", "end": "2026.11.15"},
        ):
            with self.subTest(value=value):
                Record.objects.filter(title="날짜 문서").delete()
                run = self._run_with_date(value)
                self.assertEqual(run.status, WorkbotRun.Status.SUCCESS, run.summary)

    def test_bad_date_reports_property_and_value(self):
        run = self._run_with_date("이번 주 월요일")
        self.assertEqual(run.status, WorkbotRun.Status.FAILED)
        self.assertIn("일자", run.summary)
        self.assertIn("이번 주 월요일", run.summary)
