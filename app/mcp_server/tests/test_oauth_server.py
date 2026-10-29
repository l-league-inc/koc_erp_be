import hashlib
import json
from base64 import b64encode, urlsafe_b64encode
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from api.security import get_user_from_access_token
from mcp_server.oauth_server import redirect_uri_allowed

User = get_user_model()


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class RedirectAllowlistTest(TestCase):
    def test_allows_openai_plugin_callbacks(self) -> None:
        self.assertTrue(
            redirect_uri_allowed(
                "https://chatgpt.com/connector_platform_oauth_redirect"
            )
        )
        self.assertTrue(
            redirect_uri_allowed("https://chatgpt.com/connector/oauth/callback-1")
        )
        self.assertTrue(
            redirect_uri_allowed("https://chatgpt.com/connector/oauth/callback-1/extra")
        )
        self.assertTrue(
            redirect_uri_allowed("https://platform.openai.com/apps-manage/oauth")
        )
        self.assertFalse(redirect_uri_allowed("https://evil.example/steal"))
        self.assertFalse(redirect_uri_allowed("https://chatgpt.com.evil.example/oauth"))
        self.assertFalse(redirect_uri_allowed("http://chatgpt.com/connector/oauth/abc"))

    def test_platform_relay_state_and_chatgpt_client_are_accepted(self) -> None:
        from mcp_server.oauth_server import (
            _is_chatgpt_cimd_client,
            parse_authorize_request,
        )

        state = "openai_platform_oauth_relay__" + ("a" * 1200)
        parsed = parse_authorize_request(
            {
                "response_type": "code",
                "client_id": "https://chatgpt.com/oauth/client.json",
                "redirect_uri": "https://chatgpt.com/connector_platform_oauth_redirect",
                "scope": "openid email koc_erp",
                "state": state,
                "code_challenge": _challenge("a" * 43),
                "code_challenge_method": "S256",
                "resource": settings.MCP_RESOURCE_URL,
            }
        )
        self.assertEqual(parsed.state, state)
        self.assertTrue(_is_chatgpt_cimd_client(parsed.client_id))


class OAuthAuthorizationFlowTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="oauth@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
        )
        self.redirect_uri = "https://chatgpt.com/connector_platform_oauth_redirect"
        self.verifier = "a" * 43
        self.params = {
            "response_type": "code",
            "client_id": settings.MCP_OAUTH_CLIENT_ID,
            "redirect_uri": self.redirect_uri,
            "scope": "koc_erp",
            "state": "state-1",
            "code_challenge": _challenge(self.verifier),
            "code_challenge_method": "S256",
            "resource": settings.MCP_RESOURCE_URL,
        }

    def test_metadata_points_at_our_issuer(self) -> None:
        response = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["issuer"], "https://api.koc-erp.co.kr")
        self.assertEqual(
            payload["authorization_endpoint"],
            "https://api.koc-erp.co.kr/oauth/authorize",
        )
        self.assertEqual(
            payload["token_endpoint"],
            "https://api.koc-erp.co.kr/oauth/token",
        )
        self.assertNotIn("registration_endpoint", payload)
        self.assertNotIn("client_id_metadata_document_supported", payload)
        self.assertEqual(payload["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(
            payload["token_endpoint_auth_methods_supported"],
            ["client_secret_basic"],
        )
        self.assertIs(payload["authorization_response_iss_parameter_supported"], True)

    def test_rejects_unknown_redirect_without_location(self) -> None:
        params = {**self.params, "redirect_uri": "https://evil.example/steal"}
        response = self.client.get("/oauth/authorize", params)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response)

    def test_login_issues_koc_erp_jwt(self) -> None:
        response = self.client.post("/oauth/authorize", {
            **self.params,
            "email": "oauth@example.com",
            "password": "password1234!",
        })
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["iss"], ["https://api.koc-erp.co.kr"])
        self.assertEqual(query["state"], ["state-1"])
        self.assertNotIn("error", query)

        token_response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "redirect_uri": self.redirect_uri,
                "client_id": settings.MCP_OAUTH_CLIENT_ID,
                "code_verifier": self.verifier,
                "resource": settings.MCP_RESOURCE_URL,
            },
        )
        self.assertEqual(token_response.status_code, 200)
        body = token_response.json()
        decoded = jwt.decode(
            body["access_token"],
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience=settings.MCP_RESOURCE_URL,
        )
        self.assertEqual(decoded["user_id"], self.user.id)
        self.assertEqual(decoded["env"], settings.DJANGO_ENV_NAME)
        user = async_to_sync(get_user_from_access_token)(body["access_token"])
        self.assertEqual(user.id, self.user.id)

        reused = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "redirect_uri": self.redirect_uri,
                "client_id": settings.MCP_OAUTH_CLIENT_ID,
                "code_verifier": self.verifier,
            },
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(reused.json()["error"], "invalid_grant")

        refreshed = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": body["refresh_token"],
                "client_id": settings.MCP_OAUTH_CLIENT_ID,
            },
        )
        self.assertEqual(refreshed.status_code, 200)
        refreshed_user = async_to_sync(get_user_from_access_token)(
            refreshed.json()["access_token"]
        )
        self.assertEqual(refreshed_user.id, self.user.id)

    def test_wrong_verifier_and_bad_password(self) -> None:
        started = self.client.post("/oauth/authorize", {
            **self.params,
            "email": "oauth@example.com",
            "password": "password1234!",
        })
        code = parse_qs(urlsplit(started["Location"]).query)["code"][0]
        rejected = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": settings.MCP_OAUTH_CLIENT_ID,
                "code_verifier": "b" * 43,
            },
        )
        self.assertEqual(rejected.status_code, 400)

        form = self.client.post("/oauth/authorize", {
            **self.params,
            "email": "oauth@example.com",
            "password": "wrong-password",
        })
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, "이메일 또는 비밀번호가 일치하지 않습니다.")

    def test_suspended_user_stays_on_login(self) -> None:
        self.user.status = User.UserStatusChoice.SUSPENDED
        self.user.save(update_fields=["status"])
        response = self.client.post("/oauth/authorize", {
            **self.params,
            "email": "oauth@example.com",
            "password": "password1234!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "정지되었거나 탈퇴한 계정입니다.")

    @override_settings(MCP_OAUTH_CLIENT_SECRET="portal-secret")
    def test_basic_auth_accepts_configured_secret(self) -> None:
        started = self.client.post("/oauth/authorize", {
            **self.params,
            "email": "oauth@example.com",
            "password": "password1234!",
        })
        code = parse_qs(urlsplit(started["Location"]).query)["code"][0]
        credentials = b64encode(b"koc-erp-chatgpt:portal-secret").decode()
        accepted = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": self.verifier,
            },
            HTTP_AUTHORIZATION=f"Basic {credentials}",
        )
        self.assertEqual(accepted.status_code, 200)

        rejected = self.client.post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": accepted.json()["refresh_token"],
            },
            HTTP_AUTHORIZATION="Basic " + b64encode(b"koc-erp-chatgpt:wrong").decode(),
        )
        self.assertEqual(rejected.status_code, 401)

    def test_dynamic_registration_can_log_in(self) -> None:
        registered = self.client.post(
            "/oauth/register",
            data=json.dumps(
                {
                    "redirect_uris": [self.redirect_uri],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(registered.status_code, 201)
        client_id = registered.json()["client_id"]
        self.assertNotIn("client_secret", registered.json())

        started = self.client.post("/oauth/authorize", {
            **self.params,
            "client_id": client_id,
            "email": "oauth@example.com",
            "password": "password1234!",
        })
        self.assertEqual(started.status_code, 302)
        code = parse_qs(urlsplit(started["Location"]).query)["code"][0]
        token_response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": client_id,
                "code_verifier": self.verifier,
            },
        )
        self.assertEqual(token_response.status_code, 200)

        rejected = self.client.post(
            "/oauth/register",
            data=json.dumps({"redirect_uris": ["https://evil.example/steal"]}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)

    def test_unknown_client_is_rejected(self) -> None:
        response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": "missing",
                "client_id": "someone-else",
                "code_verifier": self.verifier,
                "redirect_uri": self.redirect_uri,
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_client")

    def test_login_page_offers_kakao_and_apple_without_toss(self) -> None:
        response = self.client.get("/oauth/authorize", self.params)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "카카오로 연결")
        self.assertContains(response, "애플로 연결")
        self.assertContains(response, "토스만으로 가입한 계정")
        self.assertNotContains(response, "토스로 연결")
        self.assertEqual(self.client.post("/oauth/toss/start", self.params).status_code, 404)

    @override_settings(KAKAO_REST_API_KEY="kakao-rest-key")
    def test_kakao_login_issues_code_for_existing_account(self) -> None:
        kakao_user = User.objects.create_user(
            email="kakao-oauth@example.com",
            login_method=User.LoginMethodChoices.KAKAO,
            social_user_id="4242",
            social_email="kakao-person@example.com",
            status=User.UserStatusChoice.ACTIVE,
        )
        kakao_user.set_unusable_password()
        kakao_user.save()
        started = self.client.post("/oauth/kakao/start", self.params)
        self.assertEqual(started.status_code, 302)
        query = parse_qs(urlsplit(started["Location"]).query)
        self.assertEqual(
            query["redirect_uri"],
            ["https://api.koc-erp.co.kr/oauth/kakao/callback"],
        )
        self.assertNotIn("code_challenge", query)

        profile = {
            "id": 4242,
            "kakao_account": {"email": "kakao-person@example.com"},
        }
        with patch(
            "mcp_server.social_login.httpx.AsyncClient",
            return_value=_FakeKakaoClient(profile),
        ):
            callback = self.client.get(
                "/oauth/kakao/callback",
                {"code": "kakao-code", "state": query["state"][0]},
            )
        self.assertEqual(callback.status_code, 302)
        issued = parse_qs(urlsplit(callback["Location"]).query)
        self.assertEqual(issued["state"], ["state-1"])
        token_response = self.client.post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": issued["code"][0],
                "redirect_uri": self.redirect_uri,
                "client_id": settings.MCP_OAUTH_CLIENT_ID,
                "code_verifier": self.verifier,
                "resource": settings.MCP_RESOURCE_URL,
            },
        )
        self.assertEqual(token_response.status_code, 200)
        decoded = jwt.decode(
            token_response.json()["access_token"],
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience=settings.MCP_RESOURCE_URL,
        )
        self.assertEqual(decoded["user_id"], kakao_user.id)

    @override_settings(KAKAO_REST_API_KEY="kakao-rest-key")
    def test_kakao_email_collision_stays_on_login(self) -> None:
        started = self.client.post("/oauth/kakao/start", self.params)
        state = parse_qs(urlsplit(started["Location"]).query)["state"][0]
        profile = {"id": 99, "kakao_account": {"email": "oauth@example.com"}}
        with patch(
            "mcp_server.social_login.httpx.AsyncClient",
            return_value=_FakeKakaoClient(profile),
        ):
            callback = self.client.get(
                "/oauth/kakao/callback",
                {"code": "kakao-code", "state": state},
            )
        self.assertEqual(callback.status_code, 200)
        self.assertContains(callback, "이메일 로그인을 이용해주세요.")

    @override_settings(
        APPLE_CLIENT_ID="kr.co.kocerp.web",
        APPLE_PRIVATE_KEY="unused",
        APPLE_KEY_ID="key",
        APPLE_TEAM_ID="team",
    )
    def test_apple_login_uses_cache_state_not_session(self) -> None:
        apple_user = User.objects.create_user(
            email="apple-oauth@example.com",
            login_method=User.LoginMethodChoices.APPLE,
            social_user_id="apple-sub",
            status=User.UserStatusChoice.ACTIVE,
        )
        apple_user.set_unusable_password()
        apple_user.save()
        started = self.client.post("/oauth/apple/start", self.params)
        self.assertEqual(started.status_code, 302)
        query = parse_qs(urlsplit(started["Location"]).query)
        self.assertEqual(query["response_mode"], ["form_post"])
        self.assertEqual(
            query["redirect_uri"],
            ["https://api.koc-erp.co.kr/oauth/apple/callback"],
        )
        with (
            patch(
                "mcp_server.social_login.generate_apple_client_secret",
                return_value="apple-secret",
            ),
            patch(
                "mcp_server.social_login.httpx.AsyncClient",
                return_value=_FakeAppleClient(),
            ),
            patch(
                "mcp_server.social_login.jwt.decode",
                return_value={"sub": "apple-sub", "email": "apple-person@example.com"},
            ),
        ):
            callback = self.client.post(
                "/oauth/apple/callback",
                {"code": "apple-code", "state": query["state"][0]},
            )
        self.assertEqual(callback.status_code, 302)
        issued = parse_qs(urlsplit(callback["Location"]).query)
        self.assertEqual(issued["state"], ["state-1"])
        self.assertIn("code", issued)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeKakaoClient:
    def __init__(self, profile: dict) -> None:
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return _FakeResponse(200, {"access_token": "kakao-access"})

    async def get(self, url, **kwargs):
        return _FakeResponse(200, self.profile)


class _FakeAppleClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return _FakeResponse(200, {"id_token": "apple-id-token"})
