import json
import logging
import os

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db import close_old_connections, connections

from document.models import DocumentFile, DocumentIndex, DocumentSpace
from document.storage import download_to_temp

logger = logging.getLogger(__name__)

EXTRACTED_TEXT_LIMIT = 20000
LLM_TEXT_LIMIT = 8000
MIN_LLM_CHARS = 10

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_EXTENSIONS = {".txt", ".md", ".csv"}

_SYSTEM_PROMPT = """당신은 회사 문서 검색 색인을 만드는 도우미입니다.
문서 본문을 읽고 검색에 쓸 한국어 요약과 태그를 만듭니다.
반드시 아래 JSON만 응답합니다.
{"description_ko": "3문장 이내 요약", "tags_ko": ["태그1", "태그2"]}
tags_ko는 주제와 키워드 10개 이내의 배열입니다.
"""


def extract_text(path: str, content_type: str, filename: str) -> str | None:
    """지원하는 문서면 본문을 반환하고, 그 외 형식이면 None을 반환합니다."""
    ext = os.path.splitext(filename)[1].lower()
    mime = (content_type or "").lower()
    if mime == "application/pdf" or ext == ".pdf":
        return _extract_pdf(path)
    if mime == _DOCX_MIME or ext == ".docx":
        return _extract_docx(path)
    if mime.startswith("text/") or ext in _TEXT_EXTENSIONS:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return None


def _extract_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    parts = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(parts)


def _extract_docx(path: str) -> str:
    from docx import Document

    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def summarize(text: str) -> tuple[str, str]:
    """공유 문서 본문으로 한국어 요약과 쉼표 구분 태그를 만듭니다."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("언어 모델 키가 없습니다.")
    from openai import OpenAI

    response = OpenAI(api_key=settings.OPENAI_API_KEY).chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text[:LLM_TEXT_LIMIT]},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("색인 응답을 해석하지 못했습니다.")
    description = str(payload.get("description_ko") or "").strip()
    raw_tags = payload.get("tags_ko") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags = []
    for tag in raw_tags:
        cleaned = str(tag).replace(",", " ").strip()
        if cleaned:
            tags.append(cleaned)
    return description, ",".join(tags[:10])


def refresh_search_vector(index_id: int) -> None:
    DocumentIndex.objects.filter(pk=index_id).update(
        search_vector=(
            SearchVector("description_ko", config="simple")
            + SearchVector("tags_ko", config="simple")
            + SearchVector("extracted_text", config="simple")
            + SearchVector("filename", config="simple")
        )
    )


def build_index(file_id: int) -> None:
    """문서를 받아 추출 본문과 검색 벡터를 저장합니다."""
    try:
        _build_index(file_id)
    except Exception:
        logger.exception("document index failed file_id=%s", file_id)
        DocumentIndex.objects.filter(file_id=file_id).update(
            index_status=DocumentIndex.Status.FAILED,
            error="색인에 실패했습니다.",
        )


def _build_index(file_id: int) -> None:
    file = (
        DocumentFile.objects.select_related("folder__space", "index")
        .filter(id=file_id)
        .first()
    )
    if file is None:
        return
    index = _index_of(file)
    if index is None:
        return
    index.index_status = DocumentIndex.Status.PROCESSING
    index.error = ""
    index.filename = file.original_filename
    index.save(update_fields=["index_status", "error", "filename", "updated_at"])

    suffix = os.path.splitext(file.original_filename)[1]
    path = download_to_temp(file.object_key, suffix)
    try:
        extracted = extract_text(path, file.content_type, file.original_filename)
    finally:
        if path and os.path.exists(path):
            os.remove(path)

    if extracted is None:
        _save_index(
            index,
            extracted_text="",
            description="",
            tags="",
            source=DocumentIndex.Source.LOCAL,
            status=DocumentIndex.Status.SKIPPED,
            error="",
        )
        return

    text = extracted.strip()
    personal = file.folder.space.kind == DocumentSpace.Kind.PERSONAL
    if personal or len(text) < MIN_LLM_CHARS:
        _save_index(
            index,
            extracted_text=text[:EXTRACTED_TEXT_LIMIT],
            description=text[:300],
            tags="",
            source=DocumentIndex.Source.LOCAL,
            status=DocumentIndex.Status.READY,
            error="",
        )
        return

    try:
        description, tags = summarize(text[:LLM_TEXT_LIMIT])
    except Exception:
        logger.exception("document summary failed file_id=%s", file_id)
        _save_index(
            index,
            extracted_text=text[:EXTRACTED_TEXT_LIMIT],
            description=text[:300],
            tags="",
            source=DocumentIndex.Source.LLM,
            status=DocumentIndex.Status.FAILED,
            error="요약 생성에 실패했습니다.",
        )
        return

    _save_index(
        index,
        extracted_text=text[:EXTRACTED_TEXT_LIMIT],
        description=description,
        tags=tags,
        source=DocumentIndex.Source.LLM,
        status=DocumentIndex.Status.READY,
        error="",
    )


def _save_index(
    index: DocumentIndex,
    *,
    extracted_text: str,
    description: str,
    tags: str,
    source: str,
    status: str,
    error: str,
) -> None:
    index.extracted_text = extracted_text
    index.description_ko = description
    index.tags_ko = tags
    index.index_source = source
    index.index_status = status
    index.error = error
    index.save(
        update_fields=[
            "extracted_text",
            "description_ko",
            "tags_ko",
            "filename",
            "index_source",
            "index_status",
            "error",
            "updated_at",
        ]
    )
    refresh_search_vector(index.id)


def _index_of(file: DocumentFile) -> DocumentIndex | None:
    try:
        return file.index
    except DocumentIndex.DoesNotExist:
        return None


def run_index(file_id: int) -> None:
    close_old_connections()
    try:
        build_index(file_id)
    finally:
        connections.close_all()
