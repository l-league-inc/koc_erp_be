from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from workspace.consumers import WorkspaceConsumer
from workspace.models import Database, Property, Workspace, WorkspaceMember
from workspace.utils import create_record

User = get_user_model()


class WorkspaceSocketTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="소켓", slug="socket_ws")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        self.database = Database.objects.create(
            workspace=self.workspace,
            name="업무",
            slug="tasks",
        )
        Property.objects.create(
            database=self.database,
            name="제목",
            slug="title",
            type=Property.Type.TITLE,
        )

    def _communicator(self, user):
        communicator = WebsocketCommunicator(
            WorkspaceConsumer.as_asgi(),
            f"/ws/workspace/{self.workspace.id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {"kwargs": {"workspace_id": self.workspace.id}}
        return communicator

    async def test_outsider_cannot_connect(self):
        communicator = self._communicator(self.outsider)
        connected, _subprotocol = await communicator.connect()
        self.assertFalse(connected)

    async def test_member_receives_record_change(self):
        communicator = self._communicator(self.user)
        connected, _subprotocol = await communicator.connect()
        self.assertTrue(connected)
        await sync_to_async(create_record)(self.user, self.database.id, {"title": "알림"}, "user")
        event = await communicator.receive_json_from()
        self.assertEqual(event["type"], "workspace_changed")
        self.assertEqual(event["entity"], "record")
        self.assertEqual(event["action"], "created")
        self.assertEqual(event["actor_id"], self.user.id)
        await communicator.disconnect()
