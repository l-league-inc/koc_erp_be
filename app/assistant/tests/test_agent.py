from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from assistant.api import agent_router
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

    async def test_outsider_cannot_start_session(self):
        workspace_id = await self._workspace_id()
        response = await self.client.post(
            "/session",
            json={"workspace_id": workspace_id},
            headers=self.headers(self.outsider),
        )
        self.assertEqual(response.status_code, 403)
