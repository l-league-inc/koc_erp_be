from django.test import TestCase

from mail import crypto


class MailCryptoTests(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        token = crypto.encrypt_secret("daum-app-password")
        self.assertNotEqual(token, "daum-app-password")
        self.assertNotIn("daum-app-password", token)
        self.assertEqual(crypto.decrypt_secret(token), "daum-app-password")

    def test_same_plain_produces_different_ciphertext(self):
        first = crypto.encrypt_secret("same-secret")
        second = crypto.encrypt_secret("same-secret")
        self.assertNotEqual(first, second)
        self.assertEqual(crypto.decrypt_secret(first), "same-secret")
        self.assertEqual(crypto.decrypt_secret(second), "same-secret")
