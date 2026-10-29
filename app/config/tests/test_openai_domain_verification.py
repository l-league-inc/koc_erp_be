from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


class OpenAIAppsChallengeTest(SimpleTestCase):
    def test_returns_exact_token_as_plain_text(self) -> None:
        response = self.client.get(reverse("openai-apps-challenge"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Type"],
            "text/plain; charset=utf-8",
        )
        self.assertEqual(
            response.content,
            settings.OPENAI_APPS_CHALLENGE_TOKEN.encode("utf-8"),
        )

    def test_rejects_post(self) -> None:
        response = self.client.post(reverse("openai-apps-challenge"))

        self.assertEqual(response.status_code, 405)
