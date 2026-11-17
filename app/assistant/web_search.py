"""회사 밖 정보를 찾을 때 쓰는 Tavily 검색."""

from typing import Any

from django.conf import settings
from ninja.errors import HttpError
from tavily import TavilyClient

_MAX_QUERY = 400
_CONTENT_LIMIT = 1500
_DEFAULT_RESULTS = 5
_MAX_RESULTS = 8
_TIME_RANGES = {"day", "week", "month", "year"}
_TOPICS = {"general", "news"}

TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "회사 밖에 있는 최신 정보를 웹에서 검색합니다. "
            "정부지원사업, 공고, 뉴스, 법령처럼 워크스페이스에 없는 사실을 확인할 때 씁니다. "
            "검색어는 400자 이하로 짧게 쓰고, 조건이 많으면 여러 번 나눕니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
                "include_domains": {"type": "array", "items": {"type": "string"}},
                "topic": {"type": "string", "enum": ["general", "news"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def search_web(
    query: str,
    *,
    max_results: int | None = None,
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    """Tavily Search로 웹 결과를 모아 제목, URL, 잘린 본문만 돌려줍니다."""
    text = (query or "").strip()
    if not text:
        raise HttpError(400, "검색어가 필요합니다.")
    if len(text) > _MAX_QUERY:
        raise HttpError(400, "검색어는 400자를 넘길 수 없습니다.")

    limit = _DEFAULT_RESULTS if max_results is None else max_results
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_RESULTS:
        raise HttpError(400, "결과 수는 1에서 8 사이여야 합니다.")

    period = (time_range or "").strip()
    if period and period not in _TIME_RANGES:
        raise HttpError(400, "기간은 day, week, month, year 중 하나입니다.")

    chosen_topic = (topic or "general").strip()
    if chosen_topic not in _TOPICS:
        raise HttpError(400, "주제는 general, news 중 하나입니다.")

    domains: list[str] = []
    if include_domains:
        if not isinstance(include_domains, list) or any(
            not isinstance(item, str) or not item.strip() for item in include_domains
        ):
            raise HttpError(400, "도메인은 문자열 배열이어야 합니다.")
        domains = [item.strip() for item in include_domains]

    api_key = str(getattr(settings, "TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        raise HttpError(503, "외부 검색 키가 없습니다.")

    payload: dict[str, Any] = {
        "query": text,
        "max_results": limit,
        "search_depth": "advanced",
        "topic": chosen_topic,
        "country": "south korea",
        "include_answer": False,
        "include_raw_content": False,
    }
    if period:
        payload["time_range"] = period
    if domains:
        payload["include_domains"] = domains

    try:
        response = TavilyClient(api_key=api_key).search(**payload)
    except Exception:
        raise HttpError(502, "외부 검색에 실패했습니다.") from None
    if not isinstance(response, dict):
        raise HttpError(502, "외부 검색에 실패했습니다.")

    results = []
    for item in response.get("results") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        if len(content) > _CONTENT_LIMIT:
            content = content[:_CONTENT_LIMIT]
        results.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "content": content,
                "score": item.get("score"),
            }
        )
    return {"query": text, "results": results}
