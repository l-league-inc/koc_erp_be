import json

from django.test import SimpleTestCase

from mcp_server.auth import JwtAsgiMiddleware
from mcp_server.oauth_metadata import (
    authorization_server_issuer,
    protected_resource_metadata_url,
    www_authenticate_header,
)


class OAuthMetadataViewTest(SimpleTestCase):
    def test_root_and_mcp_metadata_match(self) -> None:
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["resource"], "https://api.koc-erp.co.kr/mcp")
            self.assertEqual(
                payload["authorization_servers"],
                ["https://api.koc-erp.co.kr"],
            )
            self.assertEqual(payload["authorization_servers"], [authorization_server_issuer()])
            self.assertEqual(payload["scopes_supported"], ["koc_erp"])


class OAuthChallengeHeaderTest(SimpleTestCase):
    async def test_missing_token_advertises_metadata(self) -> None:
        sent: list[dict] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await JwtAsgiMiddleware(app)({"type": "http", "headers": []}, receive, send)

        headers = dict(sent[0]["headers"])
        self.assertEqual(sent[0]["status"], 401)
        self.assertEqual(
            headers[b"www-authenticate"].decode(),
            www_authenticate_header(),
        )
        self.assertIn(
            protected_resource_metadata_url(),
            headers[b"www-authenticate"].decode(),
        )
        self.assertEqual(
            json.loads(sent[1]["body"]),
            {"detail": "인증이 필요합니다."},
        )
