from django.test import TestCase
from config.api import router as aws_router
from user.api import router as user_router
from ninja.testing import TestAsyncClient
from django.contrib.auth import get_user_model


User = get_user_model()


class TestAWSAPI(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(aws_router)
        self.auth_client = TestAsyncClient(user_router)
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="password1234!",
            phone_number="01011112222",
        )

    async def authenticate(
        self, email="testuser@example.com", password="password1234!"
    ):
        data = {
            "email": email,
            "password": password,
        }
        response = await self.auth_client.post("/login", json=data)
        access = response.json().get("access")
        return {"Authorization": f"Bearer {access}"}

    async def test_get_aws_upload_url(self):
        """AWS S3 이미지 업로드 URL 생성 테스트"""
        headers = await self.authenticate()
        data = {
            "file_name": "test.jpg",
        }
        response = await self.client.post("/upload", json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("uploadURL", response.json())
        self.assertIn("imageURL", response.json())

    async def test_upload_file_post(self):
        """S3 파일 업로드 테스트"""
        headers = await self.authenticate()
        data = {
            "file_name": "test.jpg",
        }
        response = await self.client.post("/upload-new", json=data, headers=headers)
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("uploadURL", response.json())
        self.assertIn("imageURL", response.json())
