from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.errors import HttpError
from ninja.testing import TestAsyncClient

from assistant.agent import _dispatch
from assistant.api import agent_router
from assistant.models import AgentSession, Skill
from user.utils import get_access_token
from workspace.models import Record, RecordActivity
from workspace.seed import seed_koc_workspace

User = get_user_model()


def _fake_complete(messages, tools):
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
        activity = await sync_to_async(RecordActivity.objects.get)(record_id=record_id)
        self.assertEqual(activity.source, RecordActivity.Source.AGENT)

        listed = await self.client.get("/session", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertEqual(listed.json()[0]["id"], session_id)
        self.assertEqual(listed.json()[0]["preview"], "출근 초안을 만들었습니다.")

        detail = await self.client.get(f"/session/{session_id}", headers=self.headers())
        self.assertEqual(detail.status_code, 200, detail.json())
        self.assertEqual(
            [item["role"] for item in detail.json()["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(detail.json()["messages"][0]["content"], "오늘 출근 등록해줘")
        self.assertEqual(detail.json()["proposed_actions"][0]["status"], "confirmed")

        hidden = await self.client.get(
            f"/session/{session_id}",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(hidden.status_code, 404)

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
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = created.json()["id"]

        def _fake_attendance(messages, tools):
            tool_messages = [item for item in messages if item.get("role") == "tool"]
            if not tool_messages:
                self.assertIn("attendance", messages[0]["content"])
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
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_create",
                            "name": "propose_create_record",
                            "arguments": {
                                "database_slug": "hr",
                                "title": "출근",
                                "values": {"status": "출근", "kind": "출근"},
                            },
                        }
                    ],
                }
            return {"content": "출근 초안을 만들었습니다.", "tool_calls": []}

        with patch("assistant.agent.llm.complete", _fake_attendance):
            message = await self.client.post(
                f"/session/{session_id}/message",
                json={"content": "오늘 출근 등록해줘"},
                headers=self.headers(),
            )
        self.assertEqual(message.status_code, 200, message.json())
        self.assertEqual(message.json()["proposed_actions"][0]["kind"], "create_record")
        self.assertEqual(message.json()["proposed_actions"][0]["payload"]["database_slug"], "hr")

    async def test_skill_draft_is_saved_on_confirm(self):
        workspace_id = await self._workspace_id()
        created = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(),
        )
        session_id = created.json()["id"]

        def _fake_skill(messages, tools):
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
