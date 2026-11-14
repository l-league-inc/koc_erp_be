from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from document.admin import DocumentFileAdmin, DocumentIndexAdmin, reindex_selected
from document.indexer import index_files, pending_shared_file_ids, summarize
from document.models import DocumentFile, DocumentIndex
from document.storage import build_object_key
from document.utils import create_file, ensure_spaces
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()


class _StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _Messages:
    def __init__(self):
        self.items: list[str] = []

    def add(self, level, message, extra_tags=""):
        self.items.append(str(message))


def _completion(content: str):
    message = type("Message", (), {"content": content})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


class PendingSharedFileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="batch-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="일괄회사", slug="batch-co")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        spaces = ensure_spaces(self.user, self.workspace.id)
        self.shared_root = spaces[0]["root_folder_id"]
        self.personal_root = spaces[1]["root_folder_id"]

    def _register(self, folder_id: int, filename: str, content_type: str = "text/plain") -> int:
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

    def _set_index(self, file_id: int, **fields) -> None:
        DocumentIndex.objects.filter(file_id=file_id).update(**fields)

    def test_pending_query_keeps_shared_backlog_only(self):
        pending_id = self._register(self.shared_root, "pending.txt")
        failed_id = self._register(self.shared_root, "failed.txt")
        self._set_index(failed_id, index_status=DocumentIndex.Status.FAILED)
        ready_llm_id = self._register(self.shared_root, "ready.txt")
        self._set_index(
            ready_llm_id,
            index_status=DocumentIndex.Status.READY,
            index_source=DocumentIndex.Source.LLM,
        )
        ready_local_id = self._register(self.shared_root, "short.txt")
        self._set_index(
            ready_local_id,
            index_status=DocumentIndex.Status.READY,
            index_source=DocumentIndex.Source.LOCAL,
        )
        skipped_id = self._register(self.shared_root, "photo.png", "image/png")
        self._set_index(skipped_id, index_status=DocumentIndex.Status.SKIPPED)
        archive_id = self._register(self.shared_root, "archive.zip", "application/zip")
        self._set_index(archive_id, index_status=DocumentIndex.Status.SKIPPED)
        fresh_id = self._register(self.shared_root, "fresh.txt")
        self._set_index(fresh_id, index_status=DocumentIndex.Status.PROCESSING)
        stale_id = self._register(self.shared_root, "stale.txt")
        self._set_index(
            stale_id,
            index_status=DocumentIndex.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(minutes=16),
        )
        missing_id = self._register(self.shared_root, "missing.txt")
        DocumentIndex.objects.get(file_id=missing_id).hard_delete()
        personal_id = self._register(self.personal_root, "personal.txt")

        self.assertEqual(
            pending_shared_file_ids(),
            [pending_id, failed_id, skipped_id, stale_id, missing_id],
        )
        found = pending_shared_file_ids()
        self.assertNotIn(personal_id, found)
        self.assertNotIn(archive_id, found)

    def test_dry_run_does_not_index(self):
        file_id = self._register(self.shared_root, "policy.txt")
        out = StringIO()
        with (
            patch("document.management.commands.index_documents.index_files") as runner,
            patch("document.indexer.summarize") as summarize_mock,
        ):
            call_command("index_documents", "--dry-run", stdout=out)
        runner.assert_not_called()
        summarize_mock.assert_not_called()
        text = out.getvalue()
        self.assertIn("대상 1건", text)
        self.assertIn("policy.txt", text)
        self.assertEqual(
            DocumentIndex.objects.get(file_id=file_id).index_status,
            DocumentIndex.Status.PENDING,
        )

    def test_command_indexes_shared_backlog_with_sleep(self):
        first_id = self._register(self.shared_root, "one.txt")
        second_id = self._register(self.shared_root, "two.txt")
        personal_id = self._register(self.personal_root, "mine.txt")
        out = StringIO()
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-batch.txt"),
            patch("document.indexer.extract_text", return_value="공유 문서 본문입니다"),
            patch("document.indexer.summarize", return_value=("요약", "문서")) as summarize_mock,
            patch("document.indexer.time.sleep") as sleep,
        ):
            call_command("index_documents", "--sleep", "5", stdout=out)
        self.assertEqual(summarize_mock.call_count, 2)
        sleep.assert_called_once_with(5)
        self.assertEqual(
            DocumentIndex.objects.get(file_id=first_id).index_source,
            DocumentIndex.Source.LLM,
        )
        self.assertEqual(
            DocumentIndex.objects.get(file_id=second_id).index_status,
            DocumentIndex.Status.READY,
        )
        self.assertEqual(
            DocumentIndex.objects.get(file_id=personal_id).index_status,
            DocumentIndex.Status.PENDING,
        )
        self.assertIn("완료 2건", out.getvalue())

    def test_command_rejects_bad_limits(self):
        with self.assertRaises(CommandError):
            call_command("index_documents", "--sleep", "-1")
        with self.assertRaises(CommandError):
            call_command("index_documents", "--limit", "0")

    def test_limit_indexes_one_file(self):
        first_id = self._register(self.shared_root, "limit-a.txt")
        second_id = self._register(self.shared_root, "limit-b.txt")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-limit.txt"),
            patch("document.indexer.extract_text", return_value="공유 문서 본문입니다"),
            patch("document.indexer.summarize", return_value=("요약", "문서")),
            patch("document.indexer.time.sleep") as sleep,
        ):
            call_command("index_documents", "--limit", "1", "--sleep", "5")
        sleep.assert_not_called()
        self.assertEqual(
            DocumentIndex.objects.get(file_id=first_id).index_status,
            DocumentIndex.Status.READY,
        )
        self.assertEqual(
            DocumentIndex.objects.get(file_id=second_id).index_status,
            DocumentIndex.Status.PENDING,
        )


@override_settings(OPENAI_API_KEY="test-key", OPENAI_MODEL="gpt-4o-mini")
class SummaryRetryTests(TestCase):
    def test_rate_limit_retries_then_succeeds(self):
        calls = {"n": 0}

        def create(text: str):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _StatusError(429)
            return _completion('{"description_ko": "연차 요약", "tags_ko": ["연차"]}')

        with (
            patch("document.indexer._create_chat_completion", side_effect=create),
            patch("document.indexer.time.sleep") as sleep,
        ):
            description, tags = summarize("공유 연차 규정 본문입니다")
        self.assertEqual(description, "연차 요약")
        self.assertEqual(tags, "연차")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60])

    def test_unavailable_retries_then_succeeds(self):
        calls = {"n": 0}

        def create(text: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _StatusError(503)
            return _completion('{"description_ko": "요약", "tags_ko": ["규정"]}')

        with (
            patch("document.indexer._create_chat_completion", side_effect=create),
            patch("document.indexer.time.sleep") as sleep,
        ):
            description, _tags = summarize("공유 연차 규정 본문입니다")
        self.assertEqual(description, "요약")
        sleep.assert_called_once_with(30)

    def test_other_status_does_not_retry(self):
        with (
            patch(
                "document.indexer._create_chat_completion",
                side_effect=_StatusError(400),
            ),
            patch("document.indexer.time.sleep") as sleep,
        ):
            with self.assertRaises(_StatusError):
                summarize("공유 연차 규정 본문입니다")
        sleep.assert_not_called()


@override_settings(OPENAI_API_KEY="test-key", OPENAI_MODEL="gpt-4o-mini")
class IndexFilesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="batch-files@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="순차회사", slug="batch-files")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        spaces = ensure_spaces(self.user, self.workspace.id)
        self.shared_root = spaces[0]["root_folder_id"]

    def _register(self, filename: str, content_type: str = "text/plain") -> int:
        created = create_file(
            self.user,
            self.workspace.id,
            {
                "folder_id": self.shared_root,
                "object_key": build_object_key(self.workspace.id, filename),
                "original_filename": filename,
                "content_type": content_type,
                "size": 32,
            },
        )
        return created["id"]

    def test_rate_limit_exhaustion_continues(self):
        first_id = self._register("first.txt")
        second_id = self._register("second.txt")

        def create(text: str):
            if "첫번째" in text:
                raise _StatusError(429)
            return _completion('{"description_ko": "두번째 요약", "tags_ko": ["문서"]}')

        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-retry.txt"),
            patch(
                "document.indexer.extract_text",
                side_effect=["첫번째 문서 본문입니다", "두번째 문서 본문입니다"],
            ),
            patch("document.indexer._create_chat_completion", side_effect=create),
            patch("document.indexer.time.sleep") as sleep,
        ):
            result = index_files([first_id, second_id], 0)
        first = DocumentIndex.objects.get(file_id=first_id)
        second = DocumentIndex.objects.get(file_id=second_id)
        self.assertEqual(first.index_status, DocumentIndex.Status.FAILED)
        self.assertEqual(first.index_source, DocumentIndex.Source.LLM)
        self.assertEqual(second.index_status, DocumentIndex.Status.READY)
        self.assertEqual(second.description_ko, "두번째 요약")
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.ready, 1)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])

    def test_skipped_file_does_not_sleep(self):
        image_id = self._register("archive.zip", "application/zip")
        text_id = self._register("note.txt")
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-skip.txt"),
            patch(
                "document.indexer.extract_text",
                side_effect=[None, "공유 문서 본문입니다"],
            ),
            patch("document.indexer.summarize", return_value=("요약", "문서")) as summarize_mock,
            patch("document.indexer.time.sleep") as sleep,
        ):
            result = index_files([image_id, text_id], 5)
        summarize_mock.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.ready, 1)

    def test_skipped_image_is_reindexed(self):
        file_id = self._register("old.png", "image/png")
        DocumentIndex.objects.filter(file_id=file_id).update(index_status=DocumentIndex.Status.SKIPPED)
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-old.png"),
            patch("document.indexer._describe_image", return_value=("오래된 사진", "사진")),
        ):
            result = index_files([file_id], 0)
        self.assertEqual(result.ready, 1)
        index = DocumentIndex.objects.get(file_id=file_id)
        self.assertEqual(index.index_source, DocumentIndex.Source.LLM)
        self.assertEqual(index.description_ko, "오래된 사진")

    def test_fresh_processing_is_left_alone(self):
        file_id = self._register("busy.txt")
        DocumentIndex.objects.filter(file_id=file_id).update(
            index_status=DocumentIndex.Status.PROCESSING,
            updated_at=timezone.now(),
        )
        with patch("document.indexer.build_index") as build:
            result = index_files([file_id], 0)
        build.assert_not_called()
        self.assertEqual(result.passed, 1)

    def test_force_reindexes_ready_file(self):
        file_id = self._register("again.txt")
        DocumentIndex.objects.filter(file_id=file_id).update(
            index_status=DocumentIndex.Status.READY,
            index_source=DocumentIndex.Source.LLM,
            description_ko="이전 요약",
        )
        with (
            patch("document.indexer.download_to_temp", return_value="/tmp/missing-force.txt"),
            patch("document.indexer.extract_text", return_value="공유 문서 본문입니다"),
            patch("document.indexer.summarize", return_value=("새 요약", "문서")),
        ):
            skipped = index_files([file_id], 0)
            forced = index_files([file_id], 0, force=True)
        self.assertEqual(skipped.passed, 1)
        self.assertEqual(forced.ready, 1)
        self.assertEqual(DocumentIndex.objects.get(file_id=file_id).description_ko, "새 요약")


class ReindexAdminActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="batch-admin@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="어드민회사", slug="batch-admin")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        spaces = ensure_spaces(self.user, self.workspace.id)
        self.shared_root = spaces[0]["root_folder_id"]
        self.personal_root = spaces[1]["root_folder_id"]

    def _register(self, folder_id: int, filename: str) -> int:
        created = create_file(
            self.user,
            self.workspace.id,
            {
                "folder_id": folder_id,
                "object_key": build_object_key(self.workspace.id, filename),
                "original_filename": filename,
                "content_type": "text/plain",
                "size": 32,
            },
        )
        return created["id"]

    def _request(self):
        request = RequestFactory().get("/admin/document/documentfile/")
        request._messages = _Messages()
        return request

    def test_file_action_starts_shared_files_only(self):
        shared_id = self._register(self.shared_root, "shared.txt")
        personal_id = self._register(self.personal_root, "personal.txt")
        request = self._request()
        admin_obj = DocumentFileAdmin(DocumentFile, AdminSite())
        queryset = DocumentFile.objects.filter(id__in=[shared_id, personal_id])
        with patch("document.admin.threading.Thread") as thread:
            reindex_selected(admin_obj, request, queryset)
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"][0], [shared_id])
        self.assertEqual(thread.call_args.kwargs["kwargs"], {"force": True})
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()
        self.assertTrue(any("개인 문서 1건" in item for item in request._messages.items))
        self.assertTrue(any("1건을 백그라운드" in item for item in request._messages.items))

    def test_index_action_uses_file_ids(self):
        shared_id = self._register(self.shared_root, "indexed.txt")
        request = self._request()
        admin_obj = DocumentIndexAdmin(DocumentIndex, AdminSite())
        queryset = DocumentIndex.objects.filter(file_id=shared_id)
        with patch("document.admin.threading.Thread") as thread:
            reindex_selected(admin_obj, request, queryset)
        self.assertEqual(thread.call_args.kwargs["args"][0], [shared_id])
