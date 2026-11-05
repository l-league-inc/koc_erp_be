from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from ninja.errors import HttpError

from assistant.llm import complete, complete_json


class LlmRoutingTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="test-key", ANTHROPIC_API_KEY="")
    @patch("assistant.llm.requests.post")
    def test_openai_model_uses_responses_api(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "output_text": "확인했습니다.",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "확인했습니다."}]}],
        }
        result = complete(
            [{"role": "user", "content": "안녕"}],
            [],
            model="gpt-6.1-sol",
        )
        self.assertEqual(result["content"], "확인했습니다.")
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/responses")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "gpt-6.1-sol")
        self.assertEqual(body["reasoning"]["effort"], "low")

    @override_settings(ANTHROPIC_API_KEY="test-key")
    @patch("assistant.llm.requests.post")
    def test_anthropic_model_uses_messages_api(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "content": [{"type": "text", "text": '{"name": "알림봇"}'}],
        }
        parsed = complete_json(
            [{"role": "user", "content": "알림봇을 만들어줘"}],
            model="claude-opus-5-5",
        )
        self.assertEqual(parsed["name"], "알림봇")
        self.assertEqual(post.call_args.args[0], "https://api.anthropic.com/v1/messages")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertNotIn("thinking", body)

    @override_settings(ANTHROPIC_API_KEY="test-key")
    @patch("assistant.llm.requests.post")
    def test_haiku_does_not_send_between_tools(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "content": [{"type": "text", "text": "확인했습니다."}],
        }
        complete([{"role": "user", "content": "안녕"}], [], model="claude-haiku-5-5")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertNotIn("thinking", body)

    @override_settings(ANTHROPIC_API_KEY="test-key")
    @patch("assistant.llm.requests.post")
    def test_sonnet_turns_off_upfront_thinking(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "content": [{"type": "text", "text": "확인했습니다."}],
        }
        complete([{"role": "user", "content": "안녕"}], [], model="claude-sonnet-5-5")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["thinking"], {"type": "between_tools"})

    @override_settings(ANTHROPIC_API_KEY="")
    def test_missing_anthropic_key_is_unavailable(self):
        with self.assertRaises(HttpError) as caught:
            complete([{"role": "user", "content": "안녕"}], [], model="claude-haiku-5-5")
        self.assertEqual(caught.exception.status_code, 503)

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(HttpError) as caught:
            complete([{"role": "user", "content": "안녕"}], [], model="gpt-4o-mini")
        self.assertEqual(caught.exception.status_code, 400)
