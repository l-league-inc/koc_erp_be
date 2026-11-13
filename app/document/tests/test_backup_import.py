import unicodedata
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from document.backup_import import import_backup_documents
from document.models import DocumentFile, DocumentFolder, DocumentIndex
from document.storage import document_prefix
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()


class _FakePaginator:
    def __init__(self, objects):
        self.objects = objects

    def paginate(self, **kwargs):
        yield {"Contents": list(self.objects)}


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.copied = []
        self.deleted = []
        self.fail_keys = set()

    def get_paginator(self, name):
        return _FakePaginator(self.objects)

    def copy_object(self, **kwargs):
        if kwargs["CopySource"]["Key"] in self.fail_keys:
            raise RuntimeError("copy failed")
        self.copied.append(kwargs)

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs["Key"])


@override_settings(AWS_UPLOAD_BUCKET="koc-erp")
class BackupImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="backup-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="KOC", slug="koc-backup")
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.OWNER,
        )
        self.nfd = unicodedata.normalize("NFD", "회사기본")
        self.objects = [
            {"Key": "backup/", "Size": 0},
            {"Key": "backup/db.json", "Size": 10},
            {"Key": "backup/.DS_Store", "Size": 40},
            {"Key": f"backup/{self.nfd}/._사업자.hwp", "Size": 20},
            {"Key": f"backup/{self.nfd}/사업자등록증.pdf", "Size": 120},
            {"Key": f"backup/{self.nfd}/등기/등기사항.pdf", "Size": 80},
            {"Key": "backup/빈폴더/", "Size": 0},
        ]

    def test_copies_tree_into_shared_space(self):
        client = FakeS3(self.objects)
        result = import_backup_documents(
            workspace=self.workspace,
            user=self.user,
            client=client,
            bucket="koc-erp",
        )

        self.assertEqual(result.imported, 2)
        self.assertEqual(result.removed, 2)
        self.assertEqual(result.folders_created, 2)
        self.assertEqual(result.failed, 0)
        self.assertEqual(len(client.copied), 2)
        self.assertEqual(
            set(client.deleted),
            {
                f"backup/{self.nfd}/사업자등록증.pdf",
                f"backup/{self.nfd}/등기/등기사항.pdf",
            },
        )
        self.assertFalse(DocumentFolder.objects.filter(name="backup").exists())
        prefix = document_prefix(self.workspace.id)
        self.assertTrue(all(item["Key"].startswith(prefix) for item in client.copied))

        company = DocumentFolder.objects.get(name="회사기본", is_root=False)
        nested = DocumentFolder.objects.get(name="등기", parent=company)
        files = DocumentFile.objects.filter(folder__in=[company, nested]).order_by("original_filename")
        self.assertEqual(
            list(files.values_list("original_filename", "size", "content_type")),
            [
                ("등기사항.pdf", 80, "application/pdf"),
                ("사업자등록증.pdf", 120, "application/pdf"),
            ],
        )
        self.assertEqual(
            set(files.values_list("index__index_status", flat=True)),
            {DocumentIndex.Status.PENDING},
        )
        self.assertEqual(files.filter(uploaded_by=self.user).count(), 2)

    def test_dry_run_writes_nothing(self):
        client = FakeS3(self.objects)
        result = import_backup_documents(
            workspace=self.workspace,
            user=self.user,
            dry_run=True,
            client=client,
            bucket="koc-erp",
        )

        self.assertEqual(result.imported, 2)
        self.assertEqual(result.removed, 0)
        self.assertEqual(result.folders_created, 2)
        self.assertEqual(client.copied, [])
        self.assertEqual(client.deleted, [])
        self.assertEqual(DocumentFile.objects.count(), 0)
        self.assertEqual(DocumentFolder.objects.filter(is_root=False).count(), 0)

    def test_second_run_skips_existing_names(self):
        client = FakeS3(self.objects)
        import_backup_documents(
            workspace=self.workspace,
            user=self.user,
            client=client,
            bucket="koc-erp",
        )
        again = import_backup_documents(
            workspace=self.workspace,
            user=self.user,
            client=FakeS3(self.objects),
            bucket="koc-erp",
        )

        self.assertEqual(again.imported, 0)
        self.assertEqual(again.removed, 2)
        self.assertEqual(again.skipped_existing, 2)
        self.assertEqual(again.folders_created, 0)
        self.assertEqual(DocumentFile.objects.count(), 2)

    def test_copy_failure_does_not_register(self):
        client = FakeS3(self.objects)
        client.fail_keys.add(f"backup/{self.nfd}/사업자등록증.pdf")
        result = import_backup_documents(
            workspace=self.workspace,
            user=self.user,
            client=client,
            bucket="koc-erp",
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(client.deleted, [f"backup/{self.nfd}/등기/등기사항.pdf"])
        self.assertFalse(
            DocumentFile.objects.filter(original_filename="사업자등록증.pdf").exists()
        )

    def test_registration_failure_deletes_copied_object(self):
        client = FakeS3(self.objects)
        with patch(
            "document.backup_import.DocumentFile.objects.create",
            side_effect=RuntimeError("db"),
        ):
            result = import_backup_documents(
                workspace=self.workspace,
                user=self.user,
                client=client,
                bucket="koc-erp",
            )

        self.assertEqual(result.imported, 0)
        self.assertEqual(result.removed, 0)
        self.assertEqual(result.failed, 2)
        self.assertEqual(len(client.deleted), 2)
        self.assertTrue(all(not key.startswith("backup/") for key in client.deleted))
        self.assertEqual(DocumentFile.objects.count(), 0)

    def test_index_flag_builds_index_for_new_and_pending(self):
        client = FakeS3(self.objects)
        with patch("document.backup_import.build_index") as build:
            first = import_backup_documents(
                workspace=self.workspace,
                user=self.user,
                index=True,
                client=client,
                bucket="koc-erp",
            )
            second = import_backup_documents(
                workspace=self.workspace,
                user=self.user,
                index=True,
                client=FakeS3(self.objects),
                bucket="koc-erp",
            )

        self.assertEqual(first.indexed, 2)
        self.assertEqual(first.removed, 2)
        self.assertEqual(second.indexed, 2)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.removed, 2)
        self.assertEqual(build.call_count, 4)

    def test_command_dry_run(self):
        client = FakeS3(self.objects)
        out = StringIO()
        with patch("document.backup_import.get_s3_client", return_value=client):
            call_command(
                "import_backup_documents",
                "--workspace-id",
                str(self.workspace.id),
                "--dry-run",
                stdout=out,
            )

        self.assertIn("미리보기", out.getvalue())
        self.assertIn("등록 2건", out.getvalue())
        self.assertEqual(DocumentFile.objects.count(), 0)

    def test_command_missing_workspace(self):
        with self.assertRaises(CommandError):
            call_command(
                "import_backup_documents",
                "--workspace-slug",
                "missing",
                "--dry-run",
            )
