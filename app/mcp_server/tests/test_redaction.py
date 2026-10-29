from django.test import SimpleTestCase

from mcp_server.redaction import omit_user_integer_ids, redact


class RedactionTests(SimpleTestCase):
    def test_removes_secret_keys(self):
        payload = {
            "title": "공지",
            "password": "secret-value",
            "access": "access-token",
            "refresh_token": "refresh-token",
            "nested": {"client_secret": "hidden", "name": "회원"},
            "items": [{"token": "abc", "id": 1}],
        }
        cleaned = redact(payload)
        text = str(cleaned)
        self.assertEqual(cleaned["title"], "공지")
        self.assertEqual(cleaned["nested"]["name"], "회원")
        self.assertEqual(cleaned["items"][0]["id"], 1)
        self.assertNotIn("password", cleaned)
        self.assertNotIn("access", cleaned)
        self.assertNotIn("secret-value", text)
        self.assertNotIn("access-token", text)
        self.assertNotIn("refresh-token", text)
        self.assertNotIn("hidden", text)
        self.assertNotIn("abc", text)

    def test_omits_integer_user_id_and_keeps_email_and_name(self):
        payload = {
            "id": 1093,
            "email": "member@example.com",
            "name": "김민수",
            "profile": {"id": 44, "type": "basic"},
            "teammates": [
                {"id": 1094, "email": "partner@example.com", "name": "이파트너"}
            ],
        }
        cleaned = omit_user_integer_ids(payload)
        self.assertNotIn("id", cleaned)
        self.assertEqual(cleaned["email"], "member@example.com")
        self.assertEqual(cleaned["name"], "김민수")
        self.assertEqual(cleaned["profile"]["id"], 44)
        self.assertNotIn("id", cleaned["teammates"][0])
        self.assertEqual(cleaned["teammates"][0]["email"], "partner@example.com")
        self.assertEqual(cleaned["teammates"][0]["name"], "이파트너")
