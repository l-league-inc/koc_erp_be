import base64
from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from ninja.errors import HttpError
from ninja.testing import TestAsyncClient

from assistant import skillbook
from assistant.agent import _TOOLS, _dispatch
from estimate.compose import draft_from_payload
from estimate.errors import EstimateError
from estimate.schema import EstimateDraft
from estimate.service import document_payload
from estimate.tests.samples import example_payload
from assistant.api import agent_router
from assistant.models import AgentSession, ProposedAction, Skill
from user.utils import get_access_token
from workspace.models import Database, Property, Record, RecordActivity, Workspace
from workspace.seed import seed_koc_workspace
from workspace.utils import create_record

User = get_user_model()


def _fake_complete(messages, tools, model=None):
    if any(item.get("role") == "tool" for item in messages):
        return {"content": "출근 초안을 만들었습니다.", "tool_calls": []}
    return {
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "name": "propose_create_record",
                "arguments": {
                    "database_slug": "hr",
                    "title": "출근",
                    "values": {"status": "출근", "kind": "출근"},
                },
            }
        ],
    }


class AgentApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(agent_router)
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

    def headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token({"user_id": user.id, "env": settings.DJANGO_ENV_NAME})
        return {"Authorization": f"Bearer {token}"}

    def _ensure_database(self, workspace_id: int, slug: str, name: str) -> Database:
        workspace = Workspace.objects.get(id=workspace_id)
        return Database.objects.create(workspace=workspace, name=name, slug=slug)

    def _link_attendance(self, workspace_id: int) -> None:
        employees = self._ensure_database(workspace_id, "employees", "임직원")
        attendance = self._ensure_database(workspace_id, "attendance", "근무 기록")
        Property.objects.create(
            database=attendance,
            name="임직원",
            slug="employee",
            type=Property.Type.RELATION,
            config={"database_id": employees.id},
        )

    def _clock_workspace(self, workspace_id: int) -> tuple[Database, Database]:
        workspace = Workspace.objects.get(id=workspace_id)
        employees = Database.objects.create(workspace=workspace, name="임직원", slug="employees")
        Property.objects.create(
            database=employees, name="이름", slug="title", type=Property.Type.TITLE
        )
        Property.objects.create(
            database=employees, name="사내 이메일", slug="email", type=Property.Type.EMAIL
        )
        attendance = Database.objects.create(workspace=workspace, name="근무 기록", slug="attendance")
        Property.objects.create(
            database=attendance, name="근무기록명", slug="title", type=Property.Type.TITLE
        )
        Property.objects.create(
            database=attendance, name="근무일", slug="work_date", type=Property.Type.DATE
        )
        Property.objects.create(
            database=attendance,
            name="임직원",
            slug="employee",
            type=Property.Type.RELATION,
            config={"database_id": employees.id},
        )
        return employees, attendance

    async def _workspace_id(self) -> int:
        from workspace.api import router as workspace_router

        client = TestAsyncClient(workspace_router)
        listed = await client.get("/", headers=self.headers())
        return listed.json()[0]["id"]

    async def test_message_proposes_until_confirm(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id, "database_slug": "hr"},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        session_id = created.json()["id"]
        with patch("assistant.agent.llm.complete", _fake_complete):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "오늘 출근 등록해줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertEqual(message.json()["message"]["content"], "출근 초안을 만들었습니다.")
        action = message.json()["proposed_actions"][0]
        self.assertEqual(action["status"], "pending")
        self.assertEqual(action["payload"]["title"], "출근")
        self.assertEqual(await sync_to_async(Record.objects.filter(title="출근").count)(), 0)

        confirmed = await self.client.post(
            f"/session/{session_id}/confirm",
            json={"action_ids": [action["id"]]},
            headers=self.headers(),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.json())
        record_id = confirmed.json()["records"][0]["record_id"]
        notice = confirmed.json()["message"]["content"]
        self.assertEqual(notice, f"확정되어 반영되었습니다. 레코드 {record_id} 출근.")
        self.assertEqual(confirmed.json()["message"]["role"], "assistant")
        self.assertIsInstance(confirmed.json()["records"][0]["database_id"], int)
        activity = await sync_to_async(RecordActivity.objects.get)(record_id=record_id)
        self.assertEqual(activity.source, RecordActivity.Source.AGENT)

        listed = await self.client.get("/session", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertEqual(listed.json()[0]["id"], session_id)
        self.assertEqual(listed.json()[0]["preview"], notice)

        detail = await self.client.get(f"/session/{session_id}", headers=self.headers())
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertEqual(
            [item["role"] for item in detail.json()["messages"]],
            ["user", "assistant", "assistant"],
        )
        self.assertEqual(detail.json()["messages"][0]["content"], "오늘 출근 등록해줘")
        self.assertEqual(detail.json()["messages"][2]["content"], notice)
        self.assertEqual(detail.json()["proposed_actions"][0]["status"], "confirmed")

        hidden = await self.client.get(
            f"/session/{session_id}",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(hidden.status_code, 404)

    async def test_next_turn_sees_confirmed_draft(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id, "database_slug": "hr"},
            headers=self.headers(),
        )
        session_id = created.json()["id"]
        seen: dict[str, str] = {}

        def _latest_user(messages) -> str:
            users = [item.get("content") for item in messages if item.get("role") == "user"]
            return users[-1] if users else ""

        def _capture(messages, tools, model=None):
            if any(item.get("role") == "tool" for item in messages):
                return {"content": "출근 초안을 만들었습니다.", "tool_calls": []}
            latest = _latest_user(messages)
            if latest == "아직이야":
                seen["pending"] = messages[0]["content"]
                return {"content": "확정 전입니다.", "tool_calls": []}
            if latest == "제목 바꿔줘":
                seen["confirmed"] = messages[0]["content"]
                seen["history"] = "\n".join(
                    item.get("content") or ""
                    for item in messages
                    if item.get("role") in {"user", "assistant"}
                )
                return {"content": "저장된 출근 기록을 고치겠습니다.", "tool_calls": []}
            return _fake_complete(messages, tools, model)

        with patch("assistant.agent.llm.complete", _capture):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "오늘 출근 등록해줘"},
                headers=self.headers(),
            )
            action = message.json()["proposed_actions"][0]
            waiting = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "아직이야"},
                headers=self.headers(),
            )
            self.assertEqual(waiting.status_code, 200, waiting.json())
            confirmed = await self.client.post(
                f"/session/{session_id}/confirm",
                json={"action_ids": [action["id"]]},
                headers=self.headers(),
            )
            record_id = confirmed.json()["records"][0]["record_id"]
            follow = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "제목 바꿔줘"},
                headers=self.headers(),
            )
        self.assertEqual(follow.status_code, 200, follow.json())
        self.assertIn(f"id {action['id']} create_record pending", seen["pending"])
        self.assertIn(f"id {action['id']} create_record confirmed", seen["confirmed"])
        self.assertIn(f"record_id {record_id}", seen["confirmed"])
        self.assertIn(confirmed.json()["message"]["content"], seen["history"])

    async def test_outsider_cannot_start_session(self):
        workspace_id = await self._workspace_id()
        response = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(self.outsider),
        )
        self.assertEqual(response.status_code, 403)
        listed = await self.client.get(
            f"/session?workspace_id={workspace_id}",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(listed.status_code, 403)

    async def test_attendance_skill_is_loaded_before_draft(self):
        workspace_id = await self._workspace_id()
        database = await sync_to_async(self._ensure_database)(workspace_id, "attendance", "근무 기록")
        await sync_to_async(Property.objects.create)(
            database=database,
            name="근무기록명",
            slug="title",
            type=Property.Type.TITLE,
        )
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = created.json()["id"]

        def _fake_attendance(messages, tools, model=None):
            tool_messages = [item for item in messages if item.get("role") == "tool"]
            if not tool_messages:
                self.assertIn("attendance", messages[0]["content"])
                self.assertIn(self.user.email, messages[0]["content"])
                self.assertNotIn("# 출근", messages[0]["content"])
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_skill",
                            "name": "view_skill",
                            "arguments": {"name": "attendance"},
                        }
                    ],
                }
            if len(tool_messages) == 1:
                self.assertIn("propose_create_record", tool_messages[0]["content"])
                self.assertIn("find_self_employee", tool_messages[0]["content"])
                self.assertIn("이름을 묻지 않습니다", tool_messages[0]["content"])
                self.assertIn("employees", tool_messages[0]["content"])
                self.assertIn("`employee`", tool_messages[0]["content"])
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_create",
                            "name": "propose_create_record",
                            "arguments": {
                                "database_slug": "attendance",
                                "title": "2026-11-01 출근",
                                "values": {},
                            },
                        }
                    ],
                }
            self.assertIn('"status": "confirmed"', tool_messages[-1]["content"])
            self.assertIn("record_id", tool_messages[-1]["content"])
            return {"content": "확정 전이라 반영할 수 없습니다.", "tool_calls": []}

        with patch("assistant.agent.llm.complete", _fake_attendance):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "오늘 출근 등록해줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        action = message.json()["proposed_actions"][0]
        self.assertEqual(action["kind"], "create_record")
        self.assertEqual(action["payload"]["database_slug"], "attendance")
        self.assertEqual(action["status"], "confirmed")
        self.assertIsInstance(action["result"]["record_id"], int)
        self.assertIn("확정되어 반영되었습니다", message.json()["message"]["content"])
        self.assertNotIn("확정 전", message.json()["message"]["content"])
        self.assertEqual(
            await sync_to_async(Record.objects.filter(title="2026-11-01 출근").count)(),
            1,
        )

    async def _session_id(self, workspace_id: int) -> int:
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        return created.json()["id"]

    async def test_clock_in_word_uses_the_account_name(self):
        self.user.name = "전다운"
        await sync_to_async(self.user.save)(update_fields=["name"])
        workspace_id = await self._workspace_id()
        employees, attendance = await sync_to_async(self._clock_workspace)(workspace_id)
        person = await sync_to_async(create_record)(
            self.user,
            employees.id,
            {"title": "전다운", "values": {"email": "office@koc.kr"}},
            RecordActivity.Source.USER,
        )
        session_id = await self._session_id(workspace_id)

        def _forbid(messages, tools, model=None):
            raise AssertionError("출근은 모델 없이 저장되어야 합니다.")

        with patch("assistant.agent.llm.complete", _forbid):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "출근"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertIn("확정되어 반영되었습니다", message.json()["message"]["content"])
        action = message.json()["proposed_actions"][0]
        self.assertEqual(action["status"], "confirmed")
        self.assertEqual(action["payload"]["values"]["employee"], [person["id"]])
        self.assertTrue(action["payload"]["title"].endswith("출근"))
        with patch("assistant.agent.llm.complete", _forbid):
            again = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "출근"},
                headers=self.headers(),
            )
        self.assertEqual(again.status_code, 200, again.json())
        self.assertIn("이미 있습니다", again.json()["message"]["content"])
        self.assertEqual(again.json()["proposed_actions"], [])
        self.assertEqual(
            await sync_to_async(Record.objects.filter(database_id=attendance.id).count)(),
            1,
        )

    async def test_clock_in_word_prefers_the_account_email(self):
        self.user.name = "전다운"
        await sync_to_async(self.user.save)(update_fields=["name"])
        workspace_id = await self._workspace_id()
        employees, attendance = await sync_to_async(self._clock_workspace)(workspace_id)
        by_email = await sync_to_async(create_record)(
            self.user,
            employees.id,
            {"title": "김다른", "values": {"email": self.user.email}},
            RecordActivity.Source.USER,
        )
        await sync_to_async(create_record)(
            self.user,
            employees.id,
            {"title": "전다운", "values": {"email": "office@koc.kr"}},
            RecordActivity.Source.USER,
        )
        session_id = await self._session_id(workspace_id)

        def _forbid(messages, tools, model=None):
            raise AssertionError("출근은 모델 없이 저장되어야 합니다.")

        with patch("assistant.agent.llm.complete", _forbid):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "오늘 출근해줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertEqual(
            message.json()["proposed_actions"][0]["payload"]["values"]["employee"],
            [by_email["id"]],
        )
        self.assertEqual(
            await sync_to_async(Record.objects.filter(database_id=attendance.id).count)(),
            1,
        )

    async def test_clock_in_word_leaves_an_ambiguous_name_to_the_model(self):
        self.user.name = "전다운"
        await sync_to_async(self.user.save)(update_fields=["name"])
        workspace_id = await self._workspace_id()
        employees, attendance = await sync_to_async(self._clock_workspace)(workspace_id)
        for email in ("one@koc.kr", "two@koc.kr"):
            await sync_to_async(create_record)(
                self.user,
                employees.id,
                {"title": "전다운", "values": {"email": email}},
                RecordActivity.Source.USER,
            )
        session_id = await self._session_id(workspace_id)

        def _ask(messages, tools, model=None):
            return {"content": "같은 이름이 둘입니다.", "tool_calls": []}

        with patch("assistant.agent.llm.complete", _ask):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "출근"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertEqual(message.json()["message"]["content"], "같은 이름이 둘입니다.")
        self.assertEqual(message.json()["proposed_actions"], [])
        self.assertEqual(
            await sync_to_async(Record.objects.filter(database_id=attendance.id).count)(),
            0,
        )

    async def test_scoped_session_can_read_related_databases(self):
        workspace_id = await self._workspace_id()
        await sync_to_async(self._link_attendance)(workspace_id)
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id, "database_slug": "attendance"},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        session = await sync_to_async(AgentSession.objects.get)(id=created.json()["id"])

        schema = await sync_to_async(_dispatch)(
            session,
            self.user,
            "get_database_schema",
            {"database_slug": "employees"},
            [],
        )
        self.assertEqual(schema["slug"], "employees")
        listed = await sync_to_async(_dispatch)(session, self.user, "list_databases", {}, [])
        self.assertEqual({item["slug"] for item in listed}, {"attendance", "employees"})
        queried = await sync_to_async(_dispatch)(
            session,
            self.user,
            "query_records",
            {"database_slug": "employees"},
            [],
        )
        self.assertEqual(queried["count"], 0)

        with self.assertRaises(HttpError) as caught:
            await sync_to_async(_dispatch)(
                session,
                self.user,
                "query_records",
                {"database_slug": "hr"},
                [],
            )
        self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(HttpError) as caught:
            await sync_to_async(_dispatch)(
                session,
                self.user,
                "propose_create_record",
                {"database_slug": "employees", "title": "임직원"},
                [],
            )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_skill_draft_is_saved_on_confirm(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = created.json()["id"]

        def _fake_skill(messages, tools, model=None):
            if any(item.get("role") == "tool" for item in messages):
                return {"content": "스킬 초안을 만들었습니다.", "tool_calls": []}
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_skill",
                        "name": "propose_create_skill",
                        "arguments": {
                            "name": "field_note",
                            "description": "현장 메모를 남길 때 씁니다.",
                            "body": "daily 영역에 메모 초안을 만듭니다.",
                        },
                    }
                ],
            }

        with patch("assistant.agent.llm.complete", _fake_skill):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "현장 메모 스킬을 만들어줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        action = message.json()["proposed_actions"][0]
        self.assertEqual(action["kind"], "create_skill")
        self.assertEqual(await sync_to_async(Skill.objects.filter(name="field_note").count)(), 0)

        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(),
        )
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertNotIn("field_note", [item["name"] for item in listed.json()])

        confirmed = await self.client.post(
            f"/session/{session_id}/confirm",
            json={"action_ids": [action["id"]]},
            headers=self.headers(),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.json())
        self.assertEqual(confirmed.json()["records"], [])
        self.assertEqual(confirmed.json()["skills"][0]["name"], "field_note")

        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(),
        )
        saved = next(item for item in listed.json() if item["name"] == "field_note")
        self.assertEqual(saved["source"], "user")
        self.assertEqual(saved["body"], "daily 영역에 메모 초안을 만듭니다.")

    async def test_bundled_skill_name_and_update_are_rejected(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/skill",
            json={
                "workspace_id": workspace_id,
                "name": "attendance",
                "description": "다른 출근",
                "body": "다른 절차",
            },
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 400)

        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        stored = await sync_to_async(AgentSession.objects.get)(id=session.json()["id"])
        with self.assertRaises(HttpError) as caught:
            await sync_to_async(_dispatch)(
                stored,
                self.user,
                "propose_update_skill",
                {"name": "attendance", "body": "바꾸기"},
                [],
            )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_outsider_cannot_list_skills(self):
        workspace_id = await self._workspace_id()
        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(listed.status_code, 403)
        created = await self.client.post(
            "/skill",
            json={
                "workspace_id": workspace_id,
                "name": "field_note",
                "description": "현장 메모를 남길 때 씁니다.",
                "body": "daily 영역에 메모 초안을 만듭니다.",
            },
            headers=self.headers(self.outsider),
        )
        self.assertEqual(created.status_code, 403)

    async def test_user_selects_model_for_the_next_message(self):
        listed = await self.client.get("/model", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertEqual(listed.json()["selected"], "gpt-6-luna")
        self.assertEqual(len(listed.json()["models"]), 6)
        self.assertEqual(
            {item["provider"] for item in listed.json()["models"]},
            {"openai", "anthropic"},
        )

        saved = await self.client.put(
            "/model",
            json={"model": "claude-sonnet-5-5"},
            headers=self.headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.json())
        self.assertEqual(saved.json()["selected"], "claude-sonnet-5-5")

        rejected = await self.client.put(
            "/model",
            json={"model": "gpt-4o-mini"},
            headers=self.headers(),
        )
        self.assertEqual(rejected.status_code, 400)

        workspace_id = await self._workspace_id()
        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        seen = {}

        def _fake_model(messages, tools, model=None):
            seen["model"] = model
            return {"content": "확인했습니다.", "tool_calls": []}

        with patch("assistant.agent.llm.complete", _fake_model):
            message = await self.client.post(
                f"/session/{session.json()['id']}/message",
                json={"content": "오늘 일정 알려줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertEqual(seen["model"], "claude-sonnet-5-5")

        with patch("assistant.agent.llm.complete", _fake_model):
            overridden = await self.client.post(
                f"/session/{session.json()['id']}/message",
                json={"content": "다시 알려줘", "model": "gpt-6.1-sol"},
                headers=self.headers(),
            )
        self.assertEqual(overridden.status_code, 200, overridden.json())
        self.assertEqual(seen["model"], "gpt-6.1-sol")

    async def test_delete_session_hides_it_from_list_and_detail(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = created.json()["id"]
        deleted = await self.client.delete(
            f"/session/{session_id}",
            headers=self.headers(),
        )
        self.assertEqual(deleted.status_code, 204)
        listed = await self.client.get("/session", headers=self.headers())
        self.assertNotIn(session_id, [item["id"] for item in listed.json()])
        detail = await self.client.get(
            f"/session/{session_id}",
            headers=self.headers(),
        )
        self.assertEqual(detail.status_code, 404)
        missing = await self.client.delete("/session/999999", headers=self.headers())
        self.assertEqual(missing.status_code, 404)

    async def test_trip_proposal_folds_end_date_into_period(self):
        workspace_id = await self._workspace_id()
        trip = await sync_to_async(self._ensure_database)(workspace_id, "trip", "출장")
        await sync_to_async(Property.objects.create)(
            database=trip,
            name="출장기간",
            slug="period",
            type=Property.Type.DATE,
        )
        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id, "database_slug": "trip"},
            headers=self.headers(),
        )
        stored = await sync_to_async(AgentSession.objects.get)(id=session.json()["id"])
        action = await sync_to_async(_dispatch)(
            stored,
            self.user,
            "propose_create_record",
            {
                "database_slug": "trip",
                "title": "부산",
                "values": {"start_date": "2026-11-04", "end_date": "2026-11-06"},
            },
            [],
        )
        period = action["payload"]["values"]["period"]
        self.assertEqual(period["start"], "2026-11-04")
        self.assertEqual(period["end"], "2026-11-06")
        self.assertNotIn("end_date", action["payload"]["values"])

    async def test_mail_bundled_skill_and_send_confirm(self):
        workspace_id = await self._workspace_id()
        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(),
        )
        self.assertEqual(listed.status_code, 200, listed.json())
        mail_skill = next(item for item in listed.json() if item["name"] == "mail")
        self.assertEqual(mail_skill["source"], "bundled")
        self.assertIsNone(mail_skill["id"])

        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = session.json()["id"]
        stored = await sync_to_async(AgentSession.objects.get)(id=session_id)
        action = await sync_to_async(_dispatch)(
            stored,
            self.user,
            "propose_send_mail",
            {
                "to": ["client@example.com"],
                "subject": "회신",
                "body": "확인했습니다.",
            },
            [],
        )
        self.assertEqual(action["kind"], "send_mail")

        with patch(
            "assistant.agent.mail_service.send_message",
            return_value={
                "sender": "owner@daum.net",
                "to": ["client@example.com"],
                "cc": [],
                "bcc": [],
                "subject": "회신",
            },
        ) as sent:
            confirmed = await self.client.post(
                f"/session/{session_id}/confirm",
                json={"action_ids": [action["id"]]},
                headers=self.headers(),
            )
        self.assertEqual(confirmed.status_code, 200, confirmed.json())
        self.assertEqual(confirmed.json()["records"], [])
        self.assertEqual(confirmed.json()["skills"], [])
        self.assertEqual(confirmed.json()["mails"][0]["subject"], "회신")

    async def test_web_search_skill_reads_the_web_without_a_draft(self):
        workspace_id = await self._workspace_id()
        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(),
        )
        skill = next(item for item in listed.json() if item["name"] == "web_search")
        self.assertEqual(skill["source"], "bundled")
        self.assertIsNone(skill["id"])
        self.assertIn("정부지원사업", skill["description"])
        self.assertIn("web_search", skill["body"])
        self.assertIn("출처 URL", skill["body"])

        rejected = await self.client.post(
            "/skill",
            json={
                "workspace_id": workspace_id,
                "name": "web_search",
                "description": "다른 검색",
                "body": "다른 절차",
            },
            headers=self.headers(),
        )
        self.assertEqual(rejected.status_code, 400)

        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        stored = await sync_to_async(AgentSession.objects.get)(id=session.json()["id"])
        source = "https://www.bizinfo.go.kr/notice/123"
        with patch(
            "assistant.agent.search_web",
            return_value={
                "query": "2026 중소기업 정부지원사업",
                "results": [
                    {
                        "title": "기술혁신 지원",
                        "url": source,
                        "content": "중소기업 기술개발 지원",
                        "score": 0.8,
                    }
                ],
            },
        ) as searched:
            output = await sync_to_async(_dispatch)(
                stored,
                self.user,
                "web_search",
                {"query": "2026 중소기업 정부지원사업", "max_results": 3},
                [],
            )
        self.assertEqual(output["results"][0]["url"], source)
        searched.assert_called_once()
        self.assertEqual(searched.call_args.kwargs["max_results"], 3)
        self.assertEqual(await sync_to_async(ProposedAction.objects.count)(), 0)
        self.assertIn("web_search", [tool["function"]["name"] for tool in _TOOLS])

    async def test_estimate_skill_confirms_into_docx(self):
        workspace_id = await self._workspace_id()
        listed = await self.client.get(
            f"/skill?workspace_id={workspace_id}",
            headers=self.headers(),
        )
        estimate_skill = next(item for item in listed.json() if item["name"] == "estimate")
        self.assertEqual(estimate_skill["source"], "bundled")
        self.assertIsNone(estimate_skill["id"])
        self.assertIn("propose_create_estimate", estimate_skill["body"])
        rejected = await self.client.post(
            "/skill",
            json={
                "workspace_id": workspace_id,
                "name": "estimate",
                "description": "다른 견적서",
                "body": "다른 절차",
            },
            headers=self.headers(),
        )
        self.assertEqual(rejected.status_code, 400)

        session = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = session.json()["id"]
        stored = await sync_to_async(AgentSession.objects.get)(id=session_id)
        action = await sync_to_async(_dispatch)(
            stored,
            self.user,
            "propose_create_estimate",
            example_payload(),
            [],
        )
        self.assertEqual(action["kind"], "create_estimate")
        self.assertNotIn("total", action["payload"])
        self.assertNotIn("docx_base64", action["payload"])

        with self.assertRaises(HttpError):
            await sync_to_async(_dispatch)(
                stored,
                self.user,
                "propose_create_estimate",
                {**example_payload(), "devices": [{**example_payload()["devices"][0], "part_unit_price": None}]},
                [],
            )

        confirmed = await self.client.post(
            f"/session/{session_id}/confirm",
            json={"action_ids": [action["id"]]},
            headers=self.headers(),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.json())
        document = confirmed.json()["estimates"][0]
        self.assertEqual(document["total"], 677600)
        self.assertEqual(document["vat"], 61600)
        self.assertEqual(document["supply_amount"], 616000)
        self.assertTrue(base64.b64decode(document["docx_base64"]).startswith(b"PK"))
        self.assertEqual(confirmed.json()["records"], [])


class EstimateSkillFileTests(SimpleTestCase):
    def test_bundled_skill_points_at_the_file_tool(self):
        skills = {item["name"]: item for item in skillbook.load_bundled()}
        self.assertEqual(skills["estimate"]["source"], "bundled")
        self.assertIn("propose_create_estimate", skills["estimate"]["body"])
        self.assertIn("6대", skills["estimate"]["body"])
        self.assertIn("미리보기", skills["estimate"]["body"])
        self.assertIn("PDF", skills["estimate"]["body"])
        self.assertIn("estimate", skills["quote"]["body"])
        names = [tool["function"]["name"] for tool in _TOOLS]
        self.assertIn("propose_create_estimate", names)

    def test_confirmed_payload_becomes_docx_without_stored_amounts(self):
        draft = draft_from_payload(example_payload())
        stored = draft.model_dump(mode="json")
        self.assertNotIn("total", stored)
        self.assertNotIn("docx_base64", stored)
        document = document_payload(EstimateDraft.model_validate(stored))
        self.assertEqual(document["supply_amount"], 616000)
        self.assertEqual(document["vat"], 61600)
        self.assertEqual(document["total"], 677600)
        self.assertTrue(base64.b64decode(document["docx_base64"]).startswith(b"PK"))

    def test_missing_price_is_rejected_before_a_file(self):
        payload = example_payload()
        payload["devices"][0]["part_unit_price"] = None
        with self.assertRaisesMessage(EstimateError, "부품 단가가 필요합니다."):
            draft_from_payload(payload)
