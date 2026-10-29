from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import markdown
from django.conf import settings

SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
MD_LINK_PATTERN = re.compile(
    r"\[([^\]]+)\]\((?:\./)?([a-zA-Z0-9][a-zA-Z0-9_-]*)\.md\)"
)

AUDIENCE_FRONTEND = "frontend"
AUDIENCE_BACKEND = "backend"
AUDIENCE_ALL = "all"
VALID_AUDIENCES = {AUDIENCE_FRONTEND, AUDIENCE_BACKEND, AUDIENCE_ALL}

LOGIN_ERROR_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다."


@dataclass
class WikiPage:
    slug: str
    title: str
    audience: str
    body: str
    html: str = ""


@dataclass
class WikiSearchHit:
    page: WikiPage
    snippet: str


def get_docs_dir() -> Path:
    return Path(settings.WIKI_DOCS_DIR)


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.fullmatch(slug))


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, text[match.end() :]


def infer_audience(slug: str, meta: dict[str, str]) -> str:
    audience = meta.get("audience", "").lower()
    if audience in VALID_AUDIENCES:
        return audience
    if "frontend" in slug:
        return AUDIENCE_FRONTEND
    return AUDIENCE_BACKEND


def extract_title(slug: str, meta: dict[str, str], body: str) -> str:
    title = meta.get("title", "").strip()
    if title:
        return title
    heading = HEADING_PATTERN.search(body)
    if heading:
        return heading.group(1).strip()
    return slug.replace("-", " ").replace("_", " ")


def rewrite_internal_links(body: str) -> str:
    return MD_LINK_PATTERN.sub(r"[\1](/wiki/p/\2/)", body)


def render_markdown(body: str) -> str:
    rewritten = rewrite_internal_links(body)
    return markdown.markdown(
        rewritten,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        output_format="html",
    )


def load_page(slug: str) -> WikiPage | None:
    if not is_valid_slug(slug):
        return None

    path = get_docs_dir() / f"{slug}.md"
    try:
        path = path.resolve()
        path.relative_to(get_docs_dir().resolve())
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None

    meta, body = parse_frontmatter(text)
    return WikiPage(
        slug=slug,
        title=extract_title(slug, meta, body),
        audience=infer_audience(slug, meta),
        body=body,
        html=render_markdown(body),
    )


def list_pages() -> list[WikiPage]:
    docs_dir = get_docs_dir()
    if not docs_dir.is_dir():
        return []

    pages: list[WikiPage] = []
    for path in sorted(docs_dir.glob("*.md")):
        if not path.is_file() or not is_valid_slug(path.stem):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        pages.append(
            WikiPage(
                slug=path.stem,
                title=extract_title(path.stem, meta, body),
                audience=infer_audience(path.stem, meta),
                body=body,
            )
        )
    return pages


def group_pages(pages: list[WikiPage]) -> dict[str, list[WikiPage]]:
    groups: dict[str, list[WikiPage]] = {
        AUDIENCE_FRONTEND: [],
        AUDIENCE_BACKEND: [],
        AUDIENCE_ALL: [],
    }
    for page in pages:
        groups.setdefault(page.audience, []).append(page)
    return groups


def search_pages(query: str) -> list[WikiSearchHit]:
    normalized = query.strip().lower()
    if not normalized:
        return []

    hits: list[WikiSearchHit] = []
    for page in list_pages():
        haystack = f"{page.title}\n{page.body}"
        index = haystack.lower().find(normalized)
        if index < 0:
            continue
        start = max(index - 40, 0)
        end = min(index + len(normalized) + 40, len(haystack))
        snippet = haystack[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = f"...{snippet}"
        if end < len(haystack):
            snippet = f"{snippet}..."
        hits.append(WikiSearchHit(page=page, snippet=snippet))
    return hits
