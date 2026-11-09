from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from ninja.testing import TestAsyncClient

from notification.models import Notification
from user.utils import get_access_token
from workspace.api import router
from workspace.blocksync import assign_positions, sync_page_blocks
from workspace.models import Block, BlockComment, CollabEvent, DocumentRevision, Page, WorkspaceMember
from workspace.seed import seed_koc_workspace

User = get_user_model()


def paragraph(text: str, **extra) -> dict:
    return {"type": "paragraph", "content": {"text": text}, **extra}


class AssignPositionsTests(TestCase):
    def test_keeps_ordered_positions_and_fills_gaps(self):
        self.assertEqual(assign_positions([None, None]), [0, 1024])
        self.assertEqual(assign_positions([0, 1024, 2048]), [0, 1024, 2048])
        self.assertEqual(assign_positions([0, None, 1024]), [0, 512, 1024])
        self.assertEqual(assign_positions([0, 1024, None]), [0, 1024, 2048])

    def test_moved_block_is_the_only_one_that_changes(self):
        result = assign_positions([1024, 2048, 0])
        self.assertEqual(result[:2], [1024, 2048])
        self.assertGreater(result[2], 2048)

    def test_renumbers_when_there_is_no_room(self):
        self.assertEqual(assign_positions([0, None, 1]), [0, 1024, 2048])
        self.assertEqual(assign_positions([None, 0, 1]), [0, 1024, 2048])
        self.assertEqual(assign_positions([5, 5, 5]), [1, 3, 5])

    def test_result_is_strictly_increasing(self):
        for stored in ([3, None, None, 4], [None, 0, None], [9, 2, 7, None, 1], [None] * 5):
            result = assign_positions(stored)
            self.assertEqual(result, sorted(set(result)), stored)


class BlockSyncBase:
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )
        self.workspace = seed_koc_workspace()
        self.member = User.objects.create_user(
            email="member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="김멤버",
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=WorkspaceMember.Role.MEMBER,
        )

    def _headers(self, user=None):
        user = user or self.user
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def _page(self, name: str = "문서") -> int:
        response = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "document", "name": name},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 201, response.json())
        return response.json()["id"]

    async def _put(self, page_id: int, blocks: list, user=None, **extra):
        return await self.client.put(
            f"/page/{page_id}/block",
            json={"blocks": blocks, **extra},
            headers=self._headers(user),
        )


class PageBlockSyncTests(BlockSyncBase, TestCase):
    async def test_first_save_creates_tree_and_returns_ids_in_request_order(self):
        page_id = await self._page()
        tree = [
            paragraph("첫째"),
            {
                "type": "toggle",
                "content": {"text": "토글"},
                "children": [paragraph("자식 하나"), paragraph("자식 둘")],
            },
            paragraph("마지막"),
        ]
        saved = await self._put(page_id, tree)
        self.assertEqual(saved.status_code, 200, saved.json())
        body = saved.json()
        self.assertEqual(len(body["ids"]), 5)
        self.assertEqual(len(body["blocks"]), 5)
        self.assertEqual(body["deleted_ids"], [])
        self.assertGreater(body["seq"], 0)

        by_id = {block["id"]: block for block in body["blocks"]}
        texts = [by_id[block_id]["content"]["text"] for block_id in body["ids"]]
        self.assertEqual(texts, ["첫째", "토글", "자식 하나", "자식 둘", "마지막"])
        toggle_id = body["ids"][1]
        self.assertEqual(by_id[body["ids"][2]]["parent_id"], toggle_id)
        self.assertEqual(by_id[body["ids"][3]]["parent_id"], toggle_id)
        self.assertIsNone(by_id[body["ids"][4]]["parent_id"])

        detail = await self.client.get(f"/page/{page_id}", headers=self._headers())
        self.assertEqual(detail.json()["collab_seq"], body["seq"])
        roots = sorted(
            (item for item in detail.json()["blocks"] if item["parent_id"] is None),
            key=lambda item: item["position"],
        )
        self.assertEqual([item["content"]["text"] for item in roots], ["첫째", "토글", "마지막"])

    async def test_resave_keeps_ids_and_only_touches_changed_blocks(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("A"), paragraph("B"), paragraph("C")])).json()
        a_id, b_id, c_id = first["ids"]
        comment = await self.client.post(
            f"/block/{a_id}/comment", json={"body": "A에 댓글"}, headers=self._headers()
        )
        self.assertEqual(comment.status_code, 201, comment.json())

        second = await self._put(
            page_id,
            [
                paragraph("A", id=a_id),
                paragraph("끼움"),
                paragraph("B 수정", id=b_id),
                paragraph("C", id=c_id),
            ],
            base_seq=first["seq"],
        )
        self.assertEqual(second.status_code, 200, second.json())
        body = second.json()
        self.assertEqual(body["ids"][0], a_id)
        self.assertEqual(body["ids"][2], b_id)
        self.assertEqual(body["ids"][3], c_id)
        changed = {block["id"] for block in body["blocks"]}
        self.assertEqual(changed, {body["ids"][1], b_id})
        self.assertEqual(body["deleted_ids"], [])

        inserted = next(block for block in body["blocks"] if block["id"] == body["ids"][1])
        edited = next(block for block in body["blocks"] if block["id"] == b_id)
        self.assertEqual(edited["content"]["text"], "B 수정")
        first_position = (await sync_to_async(Block.objects.get)(id=a_id)).position
        self.assertEqual(first_position, 0)
        self.assertLess(first_position, inserted["position"])
        self.assertLess(inserted["position"], edited["position"])

        self.assertEqual(await sync_to_async(BlockComment.objects.filter(block_id=a_id).count)(), 1)

    async def test_missing_blocks_are_deleted_with_their_children(self):
        page_id = await self._page()
        first = (
            await self._put(
                page_id,
                [
                    paragraph("남김"),
                    {"type": "toggle", "content": {"text": "지움"}, "children": [paragraph("자식")]},
                ],
            )
        ).json()
        keep_id, toggle_id, child_id = first["ids"]
        second = await self._put(page_id, [paragraph("남김", id=keep_id)], base_seq=first["seq"])
        self.assertEqual(second.status_code, 200, second.json())
        self.assertEqual(sorted(second.json()["deleted_ids"]), sorted([toggle_id, child_id]))
        self.assertEqual(second.json()["blocks"], [])
        alive = await sync_to_async(list)(Block.objects.filter(page_id=page_id).values_list("id", flat=True))
        self.assertEqual(alive, [keep_id])

    async def test_moving_a_block_under_another_parent_keeps_its_id(self):
        page_id = await self._page()
        first = (
            await self._put(
                page_id,
                [
                    {"type": "toggle", "content": {"text": "토글"}},
                    paragraph("옮길 글"),
                ],
            )
        ).json()
        toggle_id, moving_id = first["ids"]
        moved = await self._put(
            page_id,
            [
                {
                    "type": "toggle",
                    "id": toggle_id,
                    "content": {"text": "토글"},
                    "children": [paragraph("옮길 글", id=moving_id)],
                }
            ],
            base_seq=first["seq"],
        )
        self.assertEqual(moved.status_code, 200, moved.json())
        self.assertEqual(moved.json()["ids"], [toggle_id, moving_id])
        block = await sync_to_async(Block.objects.get)(id=moving_id)
        self.assertEqual(block.parent_id, toggle_id)

    async def test_no_change_is_a_noop(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("그대로")])).json()
        events_before = await sync_to_async(CollabEvent.objects.filter(page_id=page_id).count)()
        again = await self._put(
            page_id, [paragraph("그대로", id=first["ids"][0])], base_seq=first["seq"]
        )
        self.assertEqual(again.status_code, 200, again.json())
        self.assertEqual(again.json()["blocks"], [])
        self.assertEqual(again.json()["deleted_ids"], [])
        self.assertEqual(again.json()["seq"], first["seq"])
        self.assertEqual(
            await sync_to_async(CollabEvent.objects.filter(page_id=page_id).count)(), events_before
        )

    async def test_stale_base_seq_is_rejected(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("처음")])).json()
        other = await self.client.post(
            f"/page/{page_id}/block",
            json={"type": "paragraph", "content": {"text": "남이 추가"}},
            headers=self._headers(self.member),
        )
        self.assertEqual(other.status_code, 201, other.json())
        stale = await self._put(
            page_id, [paragraph("처음", id=first["ids"][0])], base_seq=first["seq"]
        )
        self.assertEqual(stale.status_code, 409, stale.json())
        remaining = await sync_to_async(Block.objects.filter(page_id=page_id).count)()
        self.assertEqual(remaining, 2)

        detail = await self.client.get(f"/page/{page_id}", headers=self._headers())
        current = detail.json()["collab_seq"]
        self.assertGreater(current, first["seq"])
        fine = await self._put(
            page_id,
            [paragraph("처음", id=first["ids"][0]), paragraph("남이 추가", id=other.json()["id"])],
            base_seq=current,
        )
        self.assertEqual(fine.status_code, 200, fine.json())

    async def test_invalid_trees_are_rejected_without_partial_writes(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("기존")])).json()
        existing_id = first["ids"][0]

        foreign = await self._put(page_id, [paragraph("남의 블록", id=existing_id + 9999)])
        self.assertEqual(foreign.status_code, 400, foreign.json())

        duplicated = await self._put(
            page_id, [paragraph("하나", id=existing_id), paragraph("둘", id=existing_id)]
        )
        self.assertEqual(duplicated.status_code, 400, duplicated.json())

        bad_shape = await self._put(
            page_id,
            [paragraph("기존", id=existing_id), {"type": "simple_table_row", "content": {}}],
        )
        self.assertEqual(bad_shape.status_code, 400, bad_shape.json())

        bad_content = await self._put(page_id, [{"type": "code", "content": {}}])
        self.assertEqual(bad_content.status_code, 400, bad_content.json())

        blocks = await sync_to_async(list)(
            Block.objects.filter(page_id=page_id).values_list("id", "content")
        )
        self.assertEqual(blocks, [(existing_id, {"text": "기존"})])

    async def test_other_pages_blocks_are_not_accepted(self):
        page_id = await self._page("가")
        other_page_id = await self._page("나")
        other = (await self._put(other_page_id, [paragraph("나의 블록")])).json()
        stolen = await self._put(page_id, [paragraph("훔침", id=other["ids"][0])])
        self.assertEqual(stolen.status_code, 400, stolen.json())

    async def test_admin_locked_page_denies_member_and_non_document_is_rejected(self):
        page_id = await self._page()
        locked = await self.client.patch(
            f"/page/{page_id}", json={"access": "admin"}, headers=self._headers()
        )
        self.assertEqual(locked.status_code, 200, locked.json())
        denied = await self._put(page_id, [paragraph("금지")], user=self.member)
        self.assertEqual(denied.status_code, 403, denied.json())

        folder = await self.client.post(
            f"/{self.workspace.id}/page",
            json={"kind": "folder", "name": "폴더", "slug": "docs_folder"},
            headers=self._headers(),
        )
        self.assertEqual(folder.status_code, 201, folder.json())
        wrong = await self._put(folder.json()["id"], [paragraph("폴더엔 없음")])
        self.assertEqual(wrong.status_code, 400, wrong.json())

    async def test_small_change_emits_only_changed_block_events(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph(f"줄 {n}") for n in range(10)])).json()
        before = await sync_to_async(CollabEvent.objects.filter(page_id=page_id).count)()
        tree = [paragraph(f"줄 {n}", id=block_id) for n, block_id in enumerate(first["ids"])]
        tree[3] = paragraph("고침", id=first["ids"][3])
        saved = await self._put(page_id, tree, base_seq=first["seq"])
        self.assertEqual(saved.status_code, 200, saved.json())
        events = await sync_to_async(list)(
            CollabEvent.objects.filter(page_id=page_id, seq__gt=first["seq"]).order_by("seq")
        )
        self.assertEqual([(event.action, event.block_id) for event in events], [("updated", first["ids"][3])])
        self.assertEqual(events[0].block["content"], {"text": "고침"})
        self.assertEqual(saved.json()["seq"], first["seq"] + 1)
        self.assertGreater(before, 0)

    async def test_large_change_collapses_into_one_reload(self):
        page_id = await self._page()
        saved = await self._put(page_id, [paragraph(f"줄 {n}") for n in range(50)])
        self.assertEqual(saved.status_code, 200, saved.json())
        events = await sync_to_async(list)(CollabEvent.objects.filter(page_id=page_id))
        self.assertEqual([event.action for event in events], ["reload"])
        self.assertEqual(saved.json()["seq"], 1)

    async def test_revisions_are_throttled_per_actor(self):
        page_id = await self._page()
        count = lambda: sync_to_async(DocumentRevision.objects.filter(page_id=page_id).count)()  # noqa: E731
        first = (await self._put(page_id, [paragraph("v1")])).json()
        self.assertEqual(await count(), 1)
        block_id = first["ids"][0]
        await self._put(page_id, [paragraph("v2", id=block_id)], base_seq=first["seq"])
        self.assertEqual(await count(), 1)
        detail = await self.client.get(f"/page/{page_id}", headers=self._headers())
        await self._put(
            page_id,
            [paragraph("v3", id=block_id)],
            user=self.member,
            base_seq=detail.json()["collab_seq"],
        )
        self.assertEqual(await count(), 2)
        revision = await sync_to_async(DocumentRevision.objects.order_by("-id").first)()
        self.assertEqual(revision.body["blocks"][0]["content"]["text"], "v2")

    async def test_revision_after_interval_is_created_again(self):
        from datetime import timedelta

        from django.utils import timezone

        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("v1")])).json()
        await sync_to_async(DocumentRevision.objects.filter(page_id=page_id).update)(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        await self._put(page_id, [paragraph("v2", id=first["ids"][0])], base_seq=first["seq"])
        self.assertEqual(await sync_to_async(DocumentRevision.objects.filter(page_id=page_id).count)(), 2)

    async def test_restore_always_leaves_a_revision(self):
        page_id = await self._page()
        first = (await self._put(page_id, [paragraph("처음")])).json()
        await self._put(page_id, [paragraph("나중", id=first["ids"][0])], base_seq=first["seq"])
        listed = await self.client.get(f"/page/{page_id}/revision", headers=self._headers())
        self.assertEqual(len(listed.json()), 1)
        restored = await self.client.post(
            f"/page/{page_id}/revision/{listed.json()[0]['id']}/restore", headers=self._headers()
        )
        self.assertEqual(restored.status_code, 200, restored.json())
        again = await self.client.get(f"/page/{page_id}/revision", headers=self._headers())
        self.assertEqual(len(again.json()), 2)


class RecordBlockSyncTests(BlockSyncBase, TestCase):
    async def _record(self) -> dict:
        response = await self.client.get("/database", headers=self._headers())
        sales_id = next(item["id"] for item in response.json() if item["slug"] == "sales")
        created = await self.client.post(
            f"/database/{sales_id}/record",
            json={
                "title": "본문 저장",
                "blocks": [paragraph("하나"), paragraph("둘")],
            },
            headers=self._headers(),
        )
        self.assertEqual(created.status_code, 201, created.json())
        return created.json()

    async def test_record_patch_with_ids_keeps_block_ids(self):
        record = await self._record()
        first_id, second_id = (block["id"] for block in record["blocks"])
        patched = await self.client.patch(
            f"/record/{record['id']}",
            json={
                "blocks": [
                    paragraph("하나", id=first_id),
                    paragraph("둘 수정", id=second_id),
                    paragraph("셋"),
                ]
            },
            headers=self._headers(),
        )
        self.assertEqual(patched.status_code, 200, patched.json())
        blocks = sorted(patched.json()["blocks"], key=lambda item: item["position"])
        self.assertEqual([block["id"] for block in blocks[:2]], [first_id, second_id])
        self.assertEqual([block["content"]["text"] for block in blocks], ["하나", "둘 수정", "셋"])
        self.assertIn("collab_seq", patched.json())
        self.assertGreater(patched.json()["collab_seq"], 0)

    async def test_record_patch_without_ids_replaces_like_before(self):
        record = await self._record()
        old_ids = {block["id"] for block in record["blocks"]}
        patched = await self.client.patch(
            f"/record/{record['id']}",
            json={"blocks": [paragraph("새 본문")]},
            headers=self._headers(),
        )
        self.assertEqual(patched.status_code, 200, patched.json())
        self.assertEqual([block["content"]["text"] for block in patched.json()["blocks"]], ["새 본문"])
        self.assertTrue(old_ids.isdisjoint({block["id"] for block in patched.json()["blocks"]}))

    async def test_record_patch_base_seq_conflict(self):
        record = await self._record()
        patched = await self.client.patch(
            f"/record/{record['id']}",
            json={"blocks": [paragraph("충돌")], "base_seq": 999},
            headers=self._headers(),
        )
        self.assertEqual(patched.status_code, 409, patched.json())
        detail = await self.client.get(f"/record/{record['id']}", headers=self._headers())
        self.assertEqual(len(detail.json()["blocks"]), 2)

    async def test_record_title_edit_without_blocks_leaves_blocks_alone(self):
        record = await self._record()
        patched = await self.client.patch(
            f"/record/{record['id']}", json={"title": "제목만"}, headers=self._headers()
        )
        self.assertEqual(patched.status_code, 200, patched.json())
        self.assertEqual(
            [block["id"] for block in patched.json()["blocks"]],
            [block["id"] for block in record["blocks"]],
        )


class BlockSyncCostTests(BlockSyncBase, TestCase):
    def test_query_count_does_not_grow_with_document_size(self):
        page = Page.objects.create(
            workspace=self.workspace, kind=Page.Kind.DOCUMENT, name="큰 문서", slug=""
        )
        tree = [paragraph(f"줄 {n}") for n in range(200)]
        first = sync_page_blocks(self.user, page.id, {"blocks": tree})
        edited = [paragraph(f"줄 {n}", id=block_id) for n, block_id in enumerate(first["ids"])]
        edited[100] = paragraph("고침", id=first["ids"][100])
        with CaptureQueriesContext(connection) as small:
            result = sync_page_blocks(
                self.user, page.id, {"blocks": edited, "base_seq": first["seq"]}
            )
        self.assertEqual(len(result["blocks"]), 1)
        self.assertLess(len(small), 25, [query["sql"][:80] for query in small])

        inserted = edited[:50] + [paragraph("끼움")] + edited[50:]
        with CaptureQueriesContext(connection) as insert:
            result = sync_page_blocks(
                self.user, page.id, {"blocks": inserted, "base_seq": result["seq"]}
            )
        self.assertEqual(len(result["blocks"]), 1)
        self.assertLess(len(insert), 25, [query["sql"][:80] for query in insert])


class BlockSyncMentionTests(BlockSyncBase, TransactionTestCase):
    async def test_new_user_mention_notifies_once(self):
        page_id = await self._page()
        mention = {
            "rich_text": [
                {"text": "김멤버", "mention": {"type": "user", "user_id": self.member.id}}
            ]
        }
        first = await self._put(page_id, [{"type": "paragraph", "content": mention}])
        self.assertEqual(first.status_code, 200, first.json())
        notes = await sync_to_async(list)(Notification.objects.filter(user=self.member))
        self.assertEqual(len(notes), 1)
        block_id = first.json()["ids"][0]
        self.assertEqual(
            notes[0].metadata,
            {
                "kind": "mention",
                "workspace_id": self.workspace.id,
                "target": "page",
                "target_id": page_id,
                "block_id": block_id,
            },
        )

        again = await self._put(
            page_id,
            [
                {"type": "paragraph", "id": block_id, "content": mention},
                {"type": "paragraph", "content": mention},
            ],
            base_seq=first.json()["seq"],
        )
        self.assertEqual(again.status_code, 200, again.json())
        self.assertEqual(await sync_to_async(Notification.objects.filter(user=self.member).count)(), 1)
