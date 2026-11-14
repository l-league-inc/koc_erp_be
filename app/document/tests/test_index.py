import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from document.indexer import build_index
from document.models import DocumentIndex, DocumentSpace
from document.storage import build_object_key
from document.utils import create_file, create_folder, ensure_spaces
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()


class DocumentIndexTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="index-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="색인회사", slug="index-co")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        spaces = ensure_spaces(self.user, self.workspace.id)
        self.shared_root = spaces[0]["root_folder_id"]
        self.personal_root = spaces[1]["root_folder_id"]

    def _register(self, folder_id: int, filename: str, content_type: str) -> int:
        created = create_file(
            self.user,
            self.workspace.id,
            {
                "folder_id": folder_id,
                "object_key": build_object_key(self.workspace.id, filename),
                "original_filename": filename,
                "content_type": content_type,
                "size": 32,
            },
        )
        return created["id"]

    def test_personal_index_stays_local(self):
        file_id = self._register(self.personal_root, "leave.txt", "text/plain")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-personal.txt"),
            patch("document.indexer.extract_text", return_value="연차 규정 본문"),
            patch("document.indexer.summarize") as summarize,
        ):
            build_index(file_id)
        summarize.assert_not_called()
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_source, DocumentIndex.Source.LOCAL)
        self.assertEqual(index.index_status, DocumentIndex.Status.READY)
        self.assertIn("연차", index.extracted_text)
        self.assertTrue(index.search_vector)

    def test_shared_index_uses_llm(self):
        file_id = self._register(self.shared_root, "policy.txt", "text/plain")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-shared.txt"),
            patch("document.indexer.extract_text", return_value="공유 연차 규정 본문입니다"),
            patch("document.indexer.summarize", return_value=("연차 요약", "연차,규정")) as summarize,
        ):
            build_index(file_id)
        summarize.assert_called_once()
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_source, DocumentIndex.Source.LLM)
        self.assertEqual(index.index_status, DocumentIndex.Status.READY)
        self.assertEqual(index.description_ko, "연차 요약")
        self.assertEqual(index.tags_ko, "연차,규정")

    def test_unknown_file_is_skipped(self):
        file_id = self._register(self.shared_root, "archive.zip", "application/zip")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-archive.zip"),
            patch("document.indexer._describe_image") as describe,
        ):
            build_index(file_id)
        describe.assert_not_called()
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_status, DocumentIndex.Status.SKIPPED)

    def test_shared_image_uses_vision(self):
        file_id = self._register(self.shared_root, "photo.png", "image/png")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-photo.png"),
            patch("document.indexer._describe_image", return_value=("현장 사진입니다", "현장,사진")),
        ):
            build_index(file_id)
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_status, DocumentIndex.Status.READY)
        self.assertEqual(index.index_source, DocumentIndex.Source.LLM)
        self.assertEqual(index.description_ko, "현장 사진입니다")
        self.assertIn("현장", index.extracted_text)

    def test_personal_image_stays_skipped(self):
        file_id = self._register(self.personal_root, "private.png", "image/png")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-private.png"),
            patch("document.indexer._describe_image") as describe,
        ):
            build_index(file_id)
        describe.assert_not_called()
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_status, DocumentIndex.Status.SKIPPED)
        self.assertEqual(index.index_source, DocumentIndex.Source.LOCAL)

    def test_shared_audio_transcribes_then_summarizes(self):
        file_id = self._register(self.shared_root, "meeting.mp3", "audio/mpeg")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-meeting.mp3"),
            patch("document.indexer._extract_audio_sample", return_value="/tmp/missing-sample.mp3"),
            patch("document.indexer._transcribe_with_whisper", return_value="회의에서 연차 규정을 설명했습니다"),
            patch("document.indexer.summarize", return_value=("연차 회의", "연차,회의")) as summarize,
        ):
            build_index(file_id)
        summarize.assert_called_once()
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_status, DocumentIndex.Status.READY)
        self.assertEqual(index.index_source, DocumentIndex.Source.LLM)
        self.assertEqual(index.description_ko, "연차 회의")
        self.assertIn("연차 규정", index.extracted_text)

    def test_shared_video_merges_frames(self):
        file_id = self._register(self.shared_root, "visit.mp4", "video/mp4")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-visit.mp4"),
            patch("document.indexer._extract_video_frames", return_value=["/tmp/frame-a.jpg", "/tmp/frame-b.jpg"]),
            patch(
                "document.indexer._describe_image",
                side_effect=[("첫째 현장입니다", "회의,현장"), ("둘째 장면입니다", "현장,사람")],
            ),
            patch("document.indexer.time.sleep") as sleep,
        ):
            build_index(file_id)
        sleep.assert_called_once_with(5)
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.description_ko, "첫째 현장입니다")
        self.assertEqual(index.tags_ko, "회의,현장,사람")
        self.assertIn("둘째", index.extracted_text)

    def test_extract_reads_text_file(self):
        from document.indexer import extract_text

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("현장 점검표")
            path = handle.name
        try:
            self.assertIn("점검표", extract_text(path, "text/plain", "check.txt"))
        finally:
            os.remove(path)


class DocumentSearchIsolationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="search-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.member = User.objects.create_user(
            email="search-member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="검색회사", slug="search-co")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceMember.Role.OWNER,
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=WorkspaceMember.Role.MEMBER,
        )

    def _add(self, user, root_id: int, filename: str, text: str) -> None:
        created = create_file(
            user,
            self.workspace.id,
            {
                "folder_id": root_id,
                "object_key": build_object_key(self.workspace.id, filename),
                "original_filename": filename,
                "content_type": "text/plain",
                "size": 20,
            },
        )
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-search.txt"),
            patch("document.indexer.extract_text", return_value=text),
            patch("document.indexer.summarize", return_value=(text[:20], "검색")),
        ):
            build_index(created["id"])

    def test_search_hides_another_members_personal_file(self):
        from document.utils import search_files

        owner_spaces = ensure_spaces(self.owner, self.workspace.id)
        member_spaces = ensure_spaces(self.member, self.workspace.id)
        self.assertEqual(owner_spaces[0]["id"], member_spaces[0]["id"])
        self.assertNotEqual(owner_spaces[1]["id"], member_spaces[1]["id"])
        self.assertEqual(
            DocumentSpace.objects.get(id=owner_spaces[1]["id"]).kind,
            DocumentSpace.Kind.PERSONAL,
        )
        self._add(self.owner, owner_spaces[0]["root_folder_id"], "shared.txt", "공유 연차 규정")
        self._add(self.owner, owner_spaces[1]["root_folder_id"], "owner-private.txt", "소유자 개인 메모")
        self._add(self.member, member_spaces[1]["root_folder_id"], "member-private.txt", "멤버 개인 메모")

        member_hits = search_files(self.member, self.workspace.id, "메모")
        names = {item["original_filename"] for item in member_hits}
        self.assertEqual(names, {"member-private.txt"})

        shared_hits = search_files(self.member, self.workspace.id, "연차")
        shared_names = {item["original_filename"] for item in shared_hits}
        self.assertIn("shared.txt", shared_names)
        self.assertNotIn("owner-private.txt", shared_names)
        self.assertTrue(shared_hits[0]["folder_path"] == "")
        folder = create_folder(
            self.owner,
            self.workspace.id,
            owner_spaces[0]["root_folder_id"],
            "계약",
        )
        self._add(self.owner, folder["id"], "contract.txt", "계약 연차 특약")
        nested = search_files(self.member, self.workspace.id, "특약")
        self.assertEqual(nested[0]["folder_path"], "계약")
