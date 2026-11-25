from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from mail.admin import UserMailAccountForm
from mail.crypto import decrypt_secret
from mail.models import UserMailAccount

User = get_user_model()


class MailAdminFormTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="mail-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )

    def _data(self, **extra):
        payload = {
            "user": self.owner.id,
            "provider": UserMailAccount.Provider.DAUM,
            "username": "daumid",
            "app_password": "plain-app-password",
            "is_verified": False,
            "last_error": "",
        }
        payload.update(extra)
        return payload

    def test_create_stores_encrypted_password(self):
        form = UserMailAccountForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()
        self.assertNotEqual(account.password_encrypted, "plain-app-password")
        self.assertNotIn("plain-app-password", account.password_encrypted)
        self.assertEqual(decrypt_secret(account.password_encrypted), "plain-app-password")

    def test_create_without_password_is_rejected(self):
        form = UserMailAccountForm(data=self._data(app_password=""))
        self.assertFalse(form.is_valid())
        self.assertIn("app_password", form.errors)

    def test_blank_password_keeps_existing_ciphertext(self):
        created = UserMailAccountForm(data=self._data()).save()
        original = created.password_encrypted
        form = UserMailAccountForm(
            data=self._data(app_password="", username="renamed"),
            instance=created,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.username, "renamed")
        self.assertEqual(saved.password_encrypted, original)
        self.assertEqual(decrypt_secret(saved.password_encrypted), "plain-app-password")

    def test_new_password_replaces_ciphertext(self):
        created = UserMailAccountForm(data=self._data()).save()
        original = created.password_encrypted
        form = UserMailAccountForm(
            data=self._data(app_password="next-secret"),
            instance=created,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertNotEqual(saved.password_encrypted, original)
        self.assertNotIn("next-secret", saved.password_encrypted)
        self.assertEqual(decrypt_secret(saved.password_encrypted), "next-secret")


class MailAdminViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="mail-admin@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.owner = User.objects.create_user(
            email="mail-owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.client.force_login(self.admin)

    def test_admin_add_encrypts_and_hides_plain_password(self):
        url = reverse("admin:mail_usermailaccount_add")
        response = self.client.post(
            url,
            {
                "user": self.owner.id,
                "provider": UserMailAccount.Provider.DAUM,
                "username": "daumid",
                "app_password": "plain-app-password",
                "is_verified": False,
            },
        )
        self.assertEqual(response.status_code, 302, response.content)
        account = UserMailAccount.objects.get(user=self.owner)
        self.assertNotIn("plain-app-password", account.password_encrypted)
        self.assertEqual(decrypt_secret(account.password_encrypted), "plain-app-password")

        detail = self.client.get(reverse("admin:mail_usermailaccount_change", args=[account.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "plain-app-password")
        self.assertContains(detail, account.password_encrypted)

        original = account.password_encrypted
        changed = self.client.post(
            reverse("admin:mail_usermailaccount_change", args=[account.id]),
            {
                "user": self.owner.id,
                "provider": UserMailAccount.Provider.DAUM,
                "username": "renamed",
                "app_password": "",
                "is_verified": False,
            },
        )
        self.assertEqual(changed.status_code, 302, changed.content)
        account.refresh_from_db()
        self.assertEqual(account.username, "renamed")
        self.assertEqual(account.password_encrypted, original)
        self.assertEqual(decrypt_secret(account.password_encrypted), "plain-app-password")
