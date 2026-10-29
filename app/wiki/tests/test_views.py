"""관리자 전용 문서 위키 테스트."""

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


class WikiViewTests(TestCase):
    def setUp(self) -> None:
        self.docs_dir = Path(tempfile.mkdtemp())
        (self.docs_dir / "partner_notification_frontend.md").write_text(
            "---\ntitle: 파트너 일정 알림\naudience: frontend\n---\n"
            "# 파트너 일정 알림\n\n딥링크는 todo_id 로 이동합니다.\n",
            encoding="utf-8",
        )
        (self.docs_dir / "architecture.md").write_text(
            "# 프로젝트 아키텍처\n\n백엔드 구성과 uniquesearchtokenxyz 를 설명합니다.\n",
            encoding="utf-8",
        )
        self.settings_override = override_settings(WIKI_DOCS_DIR=self.docs_dir)
        self.settings_override.enable()

        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password1234!",
            phone_number="01099999999",
        )
        self.customer = User.objects.create_user(
            email="customer@example.com",
            password="password1234!",
            phone_number="01011112222",
        )

    def tearDown(self) -> None:
        self.settings_override.disable()
        shutil.rmtree(self.docs_dir, ignore_errors=True)

    def login_admin(self):
        return self.client.post(
            reverse("wiki-login"),
            {"email": "admin@example.com", "password": "password1234!"},
        )

    def test_unauthenticated_index_redirects_to_login(self) -> None:
        response = self.client.get(reverse("wiki-index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("wiki-login"), response.url)

    def test_customer_login_is_rejected(self) -> None:
        response = self.client.post(
            reverse("wiki-login"),
            {"email": "customer@example.com", "password": "password1234!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "이메일 또는 비밀번호가 올바르지 않습니다.")
        follow = self.client.get(reverse("wiki-index"))
        self.assertEqual(follow.status_code, 302)

    def test_admin_login_lists_docs(self) -> None:
        response = self.login_admin()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("wiki-index"))

        index = self.client.get(reverse("wiki-index"))
        self.assertEqual(index.status_code, 200)
        self.assertContains(index, "파트너 일정 알림")
        self.assertContains(index, "프로젝트 아키텍처")

        page = self.client.get(
            reverse("wiki-page", kwargs={"slug": "partner_notification_frontend"})
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "todo_id")

    def test_invalid_slug_is_not_found(self) -> None:
        self.login_admin()
        response = self.client.get("/wiki/p/../secret/")
        self.assertEqual(response.status_code, 404)

        missing = self.client.get(reverse("wiki-page", kwargs={"slug": "not-a-real-page"}))
        self.assertEqual(missing.status_code, 404)

        dotted = self.client.get("/wiki/p/secret.md/")
        self.assertEqual(dotted.status_code, 404)

    def test_search_finds_body_keyword(self) -> None:
        self.login_admin()
        response = self.client.get(reverse("wiki-index"), {"q": "uniquesearchtokenxyz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "프로젝트 아키텍처")
        self.assertContains(response, "uniquesearchtokenxyz")

    def test_logout_blocks_access(self) -> None:
        self.login_admin()
        self.assertEqual(self.client.get(reverse("wiki-index")).status_code, 200)

        logout = self.client.get(reverse("wiki-logout"))
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.url, reverse("wiki-login"))

        again = self.client.get(reverse("wiki-index"))
        self.assertEqual(again.status_code, 302)
        self.assertIn(reverse("wiki-login"), again.url)
