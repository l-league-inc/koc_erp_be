import hashlib
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, override_settings
from ninja.testing import TestClient

from drive.api import router
from drive.models import DriveRelease
from drive.services import publish_release


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

    def test_publish_rejects_zip_and_bad_version(self):
        with self.assertRaises(ValueError):
            publish_release(version="1.2", notes="", package=BytesIO(b"PK\x03\x04"), make_current=True)
        with self.assertRaises(ValueError):
            publish_release(version="latest", notes="", package=BytesIO(b"MZ"), make_current=True)
