from unittest.mock import patch

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.testing import TestAsyncClient

from document.api import router
from document.models import DocumentChange, DocumentDownload, DocumentFile, DocumentMailLog
from document.storage import document_prefix
from user.utils import get_access_token
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()


class DocumentApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(router)
        self.owner = User.objects.create_user(
            email="doc-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.member = User.objects.create_user(
            email="doc-member@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.admin = User.objects.create_user(
            email="doc-admin@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.outsider = User.objects.create_user(
            email="doc-outsider@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.other = User.objects.create_user(
            email="doc-other@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="문서회사", slug="doc-co")
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
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.admin,
            role=WorkspaceMember.Role.ADMIN,
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.other,
            role=WorkspaceMember.Role.MEMBER,
        )

    def headers(self, user=None, *, mcp=False):
        user = user or self.owner
        token, _expires = get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        data = {"Authorization": f"Bearer {token}"}
        if mcp:
            data["X-KOC-Client"] = "mcp"
        return data

    async def _spaces(self, user=None):
        response = await self.client.get(
            f"/{self.workspace.id}/space",
            headers=self.headers(user),
        )
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()

    async def test_outsider_cannot_open_spaces(self):
        response = await self.client.get(
            f"/{self.workspace.id}/space",
            headers=self.headers(self.outsider),
        )
        self.assertEqual(response.status_code, 403)

    async def test_personal_space_is_hidden_from_admin(self):
        owner_spaces = await self._spaces(self.owner)
        admin_spaces = await self._spaces(self.admin)
        owner_personal = next(item for item in owner_spaces if item["kind"] == "personal")
        admin_personal = next(item for item in admin_spaces if item["kind"] == "personal")
        self.assertNotEqual(owner_personal["id"], admin_personal["id"])
        hidden = await self.client.get(
            f"/{self.workspace.id}/folder?space_id={owner_personal['id']}",
            headers=self.headers(self.admin),
        )
        self.assertEqual(hidden.status_code, 404)

    async def test_upload_key_uses_document_prefix(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            response = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": shared["root_folder_id"],
                    "file_name": "견적서.pdf",
                    "content_type": "application/pdf",
                    "size": 128,
                },
                headers=self.headers(self.member),
            )
        self.assertEqual(response.status_code, 200, response.json())
        object_key = response.json()["object_key"]
        self.assertTrue(object_key.startswith(document_prefix(self.workspace.id)))
        self.assertNotIn("images/", object_key)
        self.assertIn("견적서.pdf", object_key)

    async def test_register_list_and_reject_foreign_key(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        created = await self.client.post(
            f"/{self.workspace.id}/folder",
            json={"parent_id": shared["root_folder_id"], "name": "계약"},
            headers=self.headers(self.member),
        )
        self.assertEqual(created.status_code, 201, created.json())
        folder_id = created.json()["id"]
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": folder_id,
                    "file_name": "계약서.txt",
                    "content_type": "text/plain",
                    "size": 12,
                },
                headers=self.headers(self.member),
            )
        self.assertEqual(upload.status_code, 200, upload.json())
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": folder_id,
                "object_key": upload.json()["object_key"],
                "original_filename": "계약서.txt",
                "content_type": "text/plain",
                "size": 12,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(registered.status_code, 201, registered.json())
        self.assertEqual(registered.json()["index_status"], "pending")
        self.assertEqual(registered.json()["path"], "계약/계약서.txt")
        listed = await self.client.get(
            f"/{self.workspace.id}/file?folder_id={folder_id}",
            headers=self.headers(self.owner),
        )
        self.assertEqual(listed.status_code, 200, listed.json())
        self.assertEqual(listed.json()[0]["original_filename"], "계약서.txt")
        foreign = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": folder_id,
                "object_key": "other/documents/local/1/abcd/계약서.txt",
                "original_filename": "계약서.txt",
                "content_type": "text/plain",
                "size": 12,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(foreign.status_code, 400)

    async def test_download_log_records_user_and_mcp(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": shared["root_folder_id"],
                    "file_name": "manual.txt",
                    "content_type": "text/plain",
                    "size": 8,
                },
                headers=self.headers(self.member),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": shared["root_folder_id"],
                "object_key": upload.json()["object_key"],
                "original_filename": "manual.txt",
                "content_type": "text/plain",
                "size": 8,
            },
            headers=self.headers(self.member),
        )
        file_id = registered.json()["id"]
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://download.example/get"
            user_download = await self.client.post(
                f"/{self.workspace.id}/file/{file_id}/download",
                headers=self.headers(self.owner),
            )
            mcp_download = await self.client.post(
                f"/{self.workspace.id}/file/{file_id}/download",
                headers=self.headers(self.member, mcp=True),
            )
        self.assertEqual(user_download.status_code, 200, user_download.json())
        self.assertEqual(mcp_download.status_code, 200, mcp_download.json())
        self.assertEqual(user_download.json()["expires_in"], 300)
        sources = await sync_to_async(list)(
            DocumentDownload.objects.filter(file_id=file_id)
            .order_by("id")
            .values_list("source", flat=True)
        )
        self.assertEqual(sources, [DocumentDownload.Source.USER, DocumentDownload.Source.MCP])

    async def test_member_cannot_delete_others_file_but_admin_can(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": shared["root_folder_id"],
                    "file_name": "keep.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.member),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": shared["root_folder_id"],
                "object_key": upload.json()["object_key"],
                "original_filename": "keep.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.member),
        )
        file_id = registered.json()["id"]
        denied = await self.client.delete(
            f"/{self.workspace.id}/file/{file_id}",
            headers=self.headers(self.other),
        )
        self.assertEqual(denied.status_code, 403)
        removed = await self.client.delete(
            f"/{self.workspace.id}/file/{file_id}",
            headers=self.headers(self.admin),
        )
        self.assertEqual(removed.status_code, 204)
        exists = await DocumentFile.objects.filter(id=file_id).aexists()
        self.assertFalse(exists)

    async def test_non_empty_folder_and_cross_space_move(self):
        owner_spaces = await self._spaces(self.owner)
        shared = next(item for item in owner_spaces if item["kind"] == "shared")
        personal = next(item for item in owner_spaces if item["kind"] == "personal")
        made = await self.client.post(
            f"/{self.workspace.id}/folder",
            json={"parent_id": shared["root_folder_id"], "name": "보관"},
            headers=self.headers(self.owner),
        )
        folder_id = made.json()["id"]
        child = await self.client.post(
            f"/{self.workspace.id}/folder",
            json={"parent_id": folder_id, "name": "하위"},
            headers=self.headers(self.owner),
        )
        self.assertEqual(child.status_code, 201, child.json())
        blocked = await self.client.delete(
            f"/{self.workspace.id}/folder/{folder_id}",
            headers=self.headers(self.owner),
        )
        self.assertEqual(blocked.status_code, 400)
        moved = await self.client.patch(
            f"/{self.workspace.id}/folder/{child.json()['id']}",
            json={"parent_id": personal["root_folder_id"]},
            headers=self.headers(self.owner),
        )
        self.assertEqual(moved.status_code, 400)
        emptied = await self.client.delete(
            f"/{self.workspace.id}/folder/{child.json()['id']}",
            headers=self.headers(self.member),
        )
        self.assertEqual(emptied.status_code, 204)
        removed = await self.client.delete(
            f"/{self.workspace.id}/folder/{folder_id}",
            headers=self.headers(self.member),
        )
        self.assertEqual(removed.status_code, 204)

    async def test_mail_history_is_empty(self):
        spaces = await self._spaces(self.owner)
        shared = next(item for item in spaces if item["kind"] == "shared")
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": shared["root_folder_id"],
                    "file_name": "mail.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.owner),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": shared["root_folder_id"],
                "object_key": upload.json()["object_key"],
                "original_filename": "mail.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.owner),
        )
        file_id = registered.json()["id"]
        logs = await self.client.get(
            f"/{self.workspace.id}/file/{file_id}/mail",
            headers=self.headers(self.member),
        )
        self.assertEqual(logs.status_code, 200, logs.json())
        self.assertEqual(logs.json(), [])
        self.assertEqual(await DocumentMailLog.objects.acount(), 0)

    async def test_member_cannot_read_personal_file(self):
        spaces = await self._spaces(self.owner)
        personal = next(item for item in spaces if item["kind"] == "personal")
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": personal["root_folder_id"],
                    "file_name": "secret.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.owner),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": personal["root_folder_id"],
                "object_key": upload.json()["object_key"],
                "original_filename": "secret.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.owner),
        )
        file_id = registered.json()["id"]
        hidden = await self.client.get(
            f"/{self.workspace.id}/file/{file_id}",
            headers=self.headers(self.admin),
        )
        self.assertEqual(hidden.status_code, 404)

    async def test_rejects_duplicate_and_windows_names(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        folder = await self.client.post(
            f"/{self.workspace.id}/folder",
            json={"parent_id": shared["root_folder_id"], "name": "계약"},
            headers=self.headers(self.member),
        )
        self.assertEqual(folder.status_code, 201, folder.json())
        illegal_folder = await self.client.post(
            f"/{self.workspace.id}/folder",
            json={"parent_id": shared["root_folder_id"], "name": "a:b"},
            headers=self.headers(self.member),
        )
        self.assertEqual(illegal_folder.status_code, 400)
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            first = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": folder.json()["id"],
                    "file_name": "계약서.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.member),
            )
            second = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": folder.json()["id"],
                    "file_name": "다른계약서.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.member),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": folder.json()["id"],
                "object_key": first.json()["object_key"],
                "original_filename": "계약서.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(registered.status_code, 201, registered.json())
        duplicate = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": folder.json()["id"],
                "object_key": second.json()["object_key"],
                "original_filename": "계약서.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(duplicate.status_code, 400)
        reserved = await self.client.post(
            f"/{self.workspace.id}/upload",
            json={
                "folder_id": folder.json()["id"],
                "file_name": "CON.txt",
                "content_type": "text/plain",
                "size": 4,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(reserved.status_code, 400)

    async def test_sync_replace_cursor_and_changes(self):
        spaces = await self._spaces(self.member)
        shared = next(item for item in spaces if item["kind"] == "shared")
        cursor = await self.client.get(
            f"/{self.workspace.id}/sync-cursor?space_id={shared['id']}",
            headers=self.headers(self.member),
        )
        self.assertEqual(cursor.status_code, 200, cursor.json())
        self.assertEqual(cursor.json()["cursor"], 0)
        content_hash = "a" * 64
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            upload = await self.client.post(
                f"/{self.workspace.id}/upload",
                json={
                    "folder_id": shared["root_folder_id"],
                    "file_name": "동기화.txt",
                    "content_type": "text/plain",
                    "size": 4,
                },
                headers=self.headers(self.member),
            )
        registered = await self.client.post(
            f"/{self.workspace.id}/file",
            json={
                "folder_id": shared["root_folder_id"],
                "object_key": upload.json()["object_key"],
                "original_filename": "동기화.txt",
                "content_type": "text/plain",
                "size": 4,
                "content_hash": content_hash,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(registered.status_code, 201, registered.json())
        self.assertEqual(registered.json()["content_hash"], content_hash)
        file_id = registered.json()["id"]
        renamed = await self.client.patch(
            f"/{self.workspace.id}/file/{file_id}",
            json={"original_filename": "동기화-변경.txt"},
            headers=self.headers(self.member),
        )
        self.assertEqual(renamed.status_code, 200, renamed.json())
        self.assertEqual(renamed.json()["original_filename"], "동기화-변경.txt")
        conflict = await self.client.post(
            f"/{self.workspace.id}/file/{file_id}/upload",
            json={"content_type": "text/plain", "size": 5, "base_hash": "b" * 64},
            headers=self.headers(self.member),
        )
        self.assertEqual(conflict.status_code, 409)
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://upload.example/put"
            replace_upload = await self.client.post(
                f"/{self.workspace.id}/file/{file_id}/upload",
                json={"content_type": "text/plain", "size": 5, "base_hash": content_hash},
                headers=self.headers(self.member),
            )
        self.assertEqual(replace_upload.status_code, 200, replace_upload.json())
        replaced_hash = "c" * 64
        replaced = await self.client.post(
            f"/{self.workspace.id}/file/{file_id}/content",
            json={
                "object_key": replace_upload.json()["object_key"],
                "content_type": "text/plain",
                "size": 5,
                "base_hash": content_hash,
                "content_hash": replaced_hash,
            },
            headers=self.headers(self.member),
        )
        self.assertEqual(replaced.status_code, 200, replaced.json())
        self.assertEqual(replaced.json()["content_hash"], replaced_hash)
        with patch("document.storage.get_s3_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://download.example/get"
            sync_url = await self.client.post(
                f"/{self.workspace.id}/file/{file_id}/sync-url",
                headers=self.headers(self.member),
            )
        self.assertEqual(sync_url.status_code, 200, sync_url.json())
        self.assertEqual(sync_url.json()["url"], "https://download.example/get")
        self.assertEqual(await DocumentDownload.objects.filter(file_id=file_id).acount(), 0)
        changes = await self.client.get(
            f"/{self.workspace.id}/changes?space_id={shared['id']}&cursor=0",
            headers=self.headers(self.member),
        )
        self.assertEqual(changes.status_code, 200, changes.json())
        body = changes.json()
        self.assertEqual(
            [item["op"] for item in body["changes"]],
            ["upsert", "upsert", "upsert"],
        )
        self.assertEqual(body["changes"][0]["entity"], "file")
        self.assertEqual(body["changes"][-1]["payload"]["content_hash"], replaced_hash)
        self.assertEqual(body["next_cursor"], body["changes"][-1]["id"])
        self.assertEqual(await DocumentChange.objects.acount(), 3)
