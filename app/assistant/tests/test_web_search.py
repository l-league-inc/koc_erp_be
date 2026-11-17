from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from ninja.errors import HttpError
from ninja.testing import TestAsyncClient

from assistant.api import search_router
from assistant.web_search import search_web
from user.utils import get_access_token

User = get_user_model()


class WebSearchTests(SimpleTestCase):
    @override_settings(TAVILY_API_KEY="")
    def test_missing_key(self):
        with self.assertRaises(HttpError) as caught:
            search_web("정부지원사업")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.message, "외부 검색 키가 없습니다.")

    @override_settings(TAVILY_API_KEY="tvly-test")
    def test_query_too_long(self):
        with self.assertRaises(HttpError) as caught:
            search_web("가" * 401)
        self.assertEqual(caught.exception.status_code, 400)

    @override_settings(TAVILY_API_KEY="tvly-test")
    @patch("assistant.web_search.TavilyClient")
    def test_keeps_title_url_and_trims_content(self, client_cls):
        client_cls.return_value.search.return_value = {
            "answer": "합친 답은 넘기지 않습니다.",
            "results": [
                {
                    "title": "중소기업 지원",
                    "url": "https://www.bizinfo.go.kr/notice",
                    "content": "본" * 2000,
                    "score": 0.91,
                    "raw_content": "원문 전체",
                }
            ],
        }
        result = search_web(
            " 정부지원사업 ",
            max_results=3,
            time_range="month",
            include_domains=["bizinfo.go.kr"],
            topic="news",
        )
        self.assertEqual(result["query"], "정부지원사업")
        item = result["results"][0]
        self.assertEqual(set(item), {"title", "url", "content", "score"})
        self.assertEqual(item["title"], "중소기업 지원")
        self.assertEqual(item["url"], "https://www.bizinfo.go.kr/notice")
        self.assertEqual(len(item["content"]), 1500)
        self.assertNotIn("raw_content", item)
        client_cls.assert_called_once_with(api_key="tvly-test")
        kwargs = client_cls.return_value.search.call_args.kwargs
        self.assertEqual(kwargs["query"], "정부지원사업")
        self.assertEqual(kwargs["max_results"], 3)
        self.assertEqual(kwargs["search_depth"], "advanced")
        self.assertEqual(kwargs["country"], "south korea")
        self.assertEqual(kwargs["time_range"], "month")
        self.assertEqual(kwargs["include_domains"], ["bizinfo.go.kr"])
        self.assertEqual(kwargs["topic"], "news")
        self.assertIs(kwargs["include_answer"], False)
        self.assertIs(kwargs["include_raw_content"], False)

    @override_settings(TAVILY_API_KEY="tvly-secret")
    @patch("assistant.web_search.TavilyClient")
    def test_failure_does_not_expose_key(self, client_cls):
        client_cls.return_value.search.side_effect = RuntimeError("rejected tvly-secret")
        with self.assertRaises(HttpError) as caught:
            search_web("정부지원사업")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("tvly-secret", caught.exception.message)


class WebSearchApiTests(TestCase):
    def setUp(self):
        self.client = TestAsyncClient(search_router)
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="password1234!",
            status=User.UserStatusChoice.ACTIVE,
            name="박승원",
        )

    def headers(self):
        token, _expires = get_access_token(
            {"user_id": self.user.id, "env": settings.DJANGO_ENV_NAME}
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_requires_login(self):
        response = await self.client.post("/", json={"query": "정부지원사업"})
        self.assertEqual(response.status_code, 401)

    async def test_returns_search_results(self):
        payload = {
            "query": "2026 중소기업 정부지원사업",
            "results": [
                {
                    "title": "기술혁신 지원",
                    "url": "https://www.bizinfo.go.kr/notice/123",
                    "content": "중소기업 기술개발 지원",
                    "score": 0.8,
                }
            ],
        }
        with patch("assistant.api.search_web", return_value=payload) as searched:
            response = await self.client.post(
                "/",
                json={
                    "query": "2026 중소기업 정부지원사업",
                    "max_results": 3,
                    "time_range": "month",
                    "include_domains": ["bizinfo.go.kr"],
                    "topic": "news",
                },
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["results"][0]["url"], payload["results"][0]["url"])
        searched.assert_called_once_with(
            "2026 중소기업 정부지원사업",
            max_results=3,
            time_range="month",
            include_domains=["bizinfo.go.kr"],
            topic="news",
        )

    async def test_blank_query_is_rejected(self):
        response = await self.client.post("/", json={"query": "  "}, headers=self.headers())
        self.assertEqual(response.status_code, 400)
