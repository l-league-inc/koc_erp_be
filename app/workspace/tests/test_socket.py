from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from workspace.consumers import CollabConsumer, WorkspaceConsumer
from workspace.models import Database, Page, Property, Workspace, WorkspaceMember
from workspace.utils import create_block, create_record

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


class CollabSocketTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="editor@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )
        self.other = User.objects.create_user(
            email="peer@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="김동료",
        )
        self.outsider = User.objects.create_user(
            email="guest@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="공동", slug="collab_ws")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.other,
            role=WorkspaceMember.Role.MEMBER,
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
        self.record = create_record(self.user, self.database.id, {"title": "공동 편집"}, "user")
        self.page = Page.objects.create(
            workspace=self.workspace,
            kind=Page.Kind.DOCUMENT,
            name="메모",
        )

    def _collab(self, user, target="record", target_id=None):
        if target_id is None:
            target_id = self.record["id"] if target == "record" else self.page.id
        communicator = WebsocketCommunicator(
            CollabConsumer.as_asgi(),
            f"/ws/workspace/{self.workspace.id}/collab/{target}/{target_id}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "kwargs": {
                "workspace_id": self.workspace.id,
                "target": target,
                "target_id": target_id,
            }
        }
        return communicator

    async def _open(self, user, target="record", target_id=None):
        communicator = self._collab(user, target, target_id)
        connected, _subprotocol = await communicator.connect()
        self.assertTrue(connected)
        sync_message = await communicator.receive_json_from()
        presence = await communicator.receive_json_from()
        return communicator, sync_message, presence

    async def test_outsider_and_folder_cannot_connect(self):
        outsider = self._collab(self.outsider)
        connected, _subprotocol = await outsider.connect()
        self.assertFalse(connected)
        folder = await sync_to_async(Page.objects.create)(
            workspace=self.workspace,
            kind=Page.Kind.FOLDER,
            name="폴더",
            slug="notes",
        )
        communicator = self._collab(self.user, "page", folder.id)
        connected, _subprotocol = await communicator.connect()
        self.assertFalse(connected)

    async def test_room_syncs_block_ops_and_cursor(self):
        editor, sync_message, presence = await self._open(self.user)
        self.assertEqual(sync_message["type"], "sync")
        self.assertEqual(sync_message["blocks"], [])
        self.assertEqual(presence["users"][0]["name"], "박승원")

        peer, peer_sync, peer_presence = await self._open(self.other)
        self.assertEqual(peer_sync["target"], "record")
        self.assertEqual(len(peer_presence["users"]), 2)
        joined = await editor.receive_json_from()
        self.assertEqual(joined["type"], "presence")
        self.assertEqual(len(joined["users"]), 2)

        await peer.send_json_to(
            {
                "type": "op",
                "action": "create",
                "block": {"type": "paragraph", "content": {"text": "같이"}, "position": 0},
            }
        )
        created = await editor.receive_json_from()
        self.assertEqual(created["type"], "collab")
        self.assertEqual(created["action"], "created")
        self.assertEqual(created["actor_id"], self.other.id)
        self.assertEqual(created["block"]["content"]["text"], "같이")
        echo = await peer.receive_json_from()
        self.assertEqual(echo["block_id"], created["block_id"])

        await editor.send_json_to(
            {
                "type": "awareness",
                "cursor": {"block_id": created["block_id"], "offset": 1},
                "selection": None,
            }
        )
        cursor = await peer.receive_json_from()
        self.assertEqual(cursor["type"], "awareness")
        self.assertEqual(cursor["cursor"]["offset"], 1)
        self.assertEqual(cursor["name"], "박승원")

        await peer.send_json_to(
            {"type": "op", "action": "create", "block": {"type": "simple_table_row", "content": {}}}
        )
        error = await peer.receive_json_from()
        self.assertEqual(error["type"], "error")
        self.assertIn("표 행", error["detail"])

        await sync_to_async(create_block)(
            self.user,
            self.record["id"],
            {"type": "math_equation", "content": {"formula": "E=mc^2"}, "position": 1},
            "user",
        )
        rest_event = await editor.receive_json_from()
        self.assertEqual(rest_event["action"], "created")
        self.assertEqual(rest_event["block"]["type"], "math_equation")
        await peer.receive_json_from()

        page_editor, page_sync, _page_presence = await self._open(self.user, "page", self.page.id)
        self.assertEqual(page_sync["target"], "page")
        self.assertEqual(page_sync["target_id"], self.page.id)

        await editor.disconnect()
        await peer.disconnect()
        await page_editor.disconnect()

    async def test_admin_access_rejects_member_op(self):
        self.database.access = Database.Access.ADMIN
        await sync_to_async(self.database.save)(update_fields=["access"])
        member, _sync_message, _presence = await self._open(self.other)
        await member.send_json_to(
            {
                "type": "op",
                "action": "create",
                "block": {"type": "paragraph", "content": {"text": "금지"}, "position": 0},
            }
        )
        error = await member.receive_json_from()
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["status"], 403)
        await member.send_json_to({"type": "ping"})
        pong = await member.receive_json_from()
        self.assertEqual(pong["type"], "pong")
        await member.disconnect()

    def _collab_since(self, user, since: int):
        communicator = WebsocketCommunicator(
            CollabConsumer.as_asgi(),
            f"/ws/workspace/{self.workspace.id}/collab/record/{self.record['id']}/?since={since}",
        )
        communicator.scope["user"] = user
        communicator.scope["query_string"] = f"since={since}".encode()
        communicator.scope["url_route"] = {
            "kwargs": {
                "workspace_id": self.workspace.id,
                "target": "record",
                "target_id": self.record["id"],
            }
        }
        return communicator

    async def test_since_replays_missing_events_or_full_sync(self):
        from workspace.models import CollabEvent
        from workspace.utils import update_record

        await sync_to_async(create_block)(
            self.user,
            self.record["id"],
            {"type": "paragraph", "content": {"text": "첫 문단"}, "position": 0},
            "user",
        )
        communicator = self._collab_since(self.user, 0)
        connected, _subprotocol = await communicator.connect()
        self.assertTrue(connected)
        catchup = await communicator.receive_json_from()
        self.assertEqual(catchup["type"], "catchup")
        self.assertEqual(catchup["seq"], 1)
        self.assertEqual(len(catchup["events"]), 1)
        self.assertEqual(catchup["events"][0]["action"], "created")
        self.assertEqual(catchup["events"][0]["block"]["content"]["text"], "첫 문단")
        await communicator.receive_json_from()
        await communicator.disconnect()

        current = self._collab_since(self.user, 1)
        connected, _subprotocol = await current.connect()
        self.assertTrue(connected)
        empty = await current.receive_json_from()
        self.assertEqual(empty["type"], "catchup")
        self.assertEqual(empty["events"], [])
        await current.receive_json_from()
        await current.disconnect()

        await sync_to_async(update_record)(
            self.user,
            self.record["id"],
            {"blocks": [{"type": "paragraph", "content": {"text": "통째로"}, "position": 0}]},
            "user",
        )
        reloaded = self._collab_since(self.user, 1)
        connected, _subprotocol = await reloaded.connect()
        self.assertTrue(connected)
        full = await reloaded.receive_json_from()
        self.assertEqual(full["type"], "sync")
        self.assertEqual(full["blocks"][0]["content"]["text"], "통째로")
        await reloaded.receive_json_from()
        await reloaded.disconnect()

        await sync_to_async(CollabEvent.objects.filter(record_id=self.record["id"]).delete)()
        gap = self._collab_since(self.other, 0)
        connected, _subprotocol = await gap.connect()
        self.assertTrue(connected)
        resync = await gap.receive_json_from()
        self.assertEqual(resync["type"], "sync")
        self.assertGreater(resync["seq"], 0)
        await gap.receive_json_from()
        await gap.disconnect()
