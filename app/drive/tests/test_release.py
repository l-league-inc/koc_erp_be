import hashlib
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from ninja.testing import TestClient

from drive.api import router
from drive.models import DriveRelease
from drive.services import discard_releases, publish_release


@override_settings(AWS_UPLOAD_BUCKET="test-bucket", DJANGO_ENV_NAME="local")
class DriveReleaseTests(TestCase):
    def setUp(self):
        self.client = TestClient(router)

    def test_empty_release(self):
        response = self.client.get("/release")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "")

    def test_current_release_returns_download(self):
        DriveRelease.objects.create(
            version="1.2.0",
            notes="아이콘",
            object_key="koc/drive/local/1.2.0/KOC-ERP.exe",
            sha256="ab" * 32,
            size=12,
            is_current=True,
        )
        with patch("drive.api.presign_release", return_value="https://files.example.com/app.exe") as presign:
            response = self.client.get("/release")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["version"], "1.2.0")
        self.assertEqual(body["url"], "https://files.example.com/app.exe")
        self.assertEqual(body["notes"], "아이콘")
        presign.assert_called_once()

    def test_publish_hashes_exe_and_replaces_current(self):
        blob = b"MZ" + b"drive"
        with patch("drive.storage.get_s3_client") as client:
            first = publish_release(version="1.1.0", notes="", package=BytesIO(blob), make_current=True)
            second = publish_release(version="1.2.0", notes="수정", package=BytesIO(blob + b"!"), make_current=True)

        self.assertEqual(client.return_value.upload_fileobj.call_count, 2)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(second.sha256, hashlib.sha256(blob + b"!").hexdigest())
        self.assertEqual(second.object_key, "koc/drive/local/1.2.0/KOC-ERP.exe")
        self.assertFalse(DriveRelease.objects.get(pk=first.pk).is_current)

    def test_discard_deletes_s3_object_when_unused(self):
        release = DriveRelease.objects.create(
            version="1.0.0",
            object_key="koc/drive/local/1.0.0/KOC-ERP.exe",
            sha256="ab" * 32,
            size=4,
            is_current=False,
        )
        with patch("drive.storage.get_s3_client") as client:
            discard_releases([release])

        client.return_value.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="koc/drive/local/1.0.0/KOC-ERP.exe",
        )
        self.assertFalse(DriveRelease.objects.filter(pk=release.pk).exists())

    def test_discard_keeps_s3_object_shared_by_another_release(self):
        key = "koc/drive/local/1.1.0/KOC-ERP.exe"
        first = DriveRelease.objects.create(
            version="1.1.0",
            object_key=key,
            sha256="cd" * 32,
            size=4,
            is_current=False,
        )
        DriveRelease.objects.create(
            version="1.1.0",
            object_key=key,
            sha256="cd" * 32,
            size=4,
            is_current=True,
        )
        with patch("drive.storage.get_s3_client") as client:
            discard_releases([first])

        client.return_value.delete_object.assert_not_called()

    def test_admin_can_download_past_release(self):
        User = get_user_model()
        User.objects.create_superuser(email="drive-admin@example.com", password="password1234!")
        release = DriveRelease.objects.create(
            version="1.0.0",
            object_key="koc/drive/local/1.0.0/KOC-ERP.exe",
            sha256="ef" * 32,
            size=4,
            is_current=False,
        )
        client = Client()
        client.force_login(User.objects.get(email="drive-admin@example.com"))
        with patch("drive.admin.presign_release", return_value="https://files.example.com/old.exe") as presign:
            response = client.get(f"/admin/drive/driverelease/{release.pk}/download/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://files.example.com/old.exe")
        presign.assert_called_once_with(release.object_key, filename="KOC ERP 1.0.0.exe")

    def test_publish_rejects_zip_and_bad_version(self):
        with self.assertRaises(ValueError):
            publish_release(version="1.2", notes="", package=BytesIO(b"PK\x03\x04"), make_current=True)
        with self.assertRaises(ValueError):
            publish_release(version="latest", notes="", package=BytesIO(b"MZ"), make_current=True)
