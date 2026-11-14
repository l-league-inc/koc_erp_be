import base64
import json
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db import IntegrityError, close_old_connections, connections
from django.db.models import Q
from django.utils import timezone

from document.models import DocumentFile, DocumentIndex, DocumentSpace
from document.storage import download_to_temp

logger = logging.getLogger(__name__)

EXTRACTED_TEXT_LIMIT = 20000
LLM_TEXT_LIMIT = 8000
MIN_LLM_CHARS = 10
DEFAULT_INDEX_SLEEP_SECONDS = 5
STALE_PROCESSING = timedelta(minutes=15)
_RETRY_DELAYS = (30, 60, 120)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".m4b"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpeg", ".mpg", ".wmv"}
_VISION_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_VISION_EDGE = 1600
_AUDIO_SAMPLE_SECONDS = 180
_VIDEO_FRAME_COUNT = 4
_WHISPER_MODEL = "whisper-1"

_SYSTEM_PROMPT = """당신은 회사 문서 검색 색인을 만드는 도우미입니다.
문서 본문을 읽고 검색에 쓸 한국어 요약과 태그를 만듭니다.
반드시 아래 JSON만 응답합니다.
{"description_ko": "3문장 이내 요약", "tags_ko": ["태그1", "태그2"]}
tags_ko는 주제와 키워드 10개 이내의 배열입니다.
"""

_IMAGE_PROMPT = """당신은 회사 파일 검색 색인을 만드는 도우미입니다.
이미지를 보고 검색에 쓸 한국어 설명과 태그를 만듭니다.
반드시 아래 JSON만 응답합니다.
{"description_ko": "3문장 이내 설명", "tags_ko": ["태그1", "태그2"]}
tags_ko는 피사체, 장소, 분위기, 적힌 글자 등 10개 이내의 배열입니다.
"""


def media_kind(content_type: str, filename: str) -> str | None:
    """이미지, 오디오, 영상이면 종류를 반환하고 그 외에는 None을 반환합니다."""
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = os.path.splitext(filename or "")[1].lower()
    if mime.startswith("image/") or ext in _IMAGE_EXTENSIONS:
        return "image"
    if mime.startswith("audio/") or ext in _AUDIO_EXTENSIONS:
        return "audio"
    if mime.startswith("video/") or ext in _VIDEO_EXTENSIONS:
        return "video"
    return None


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
    response = _complete_summary(text)
    return _summary_from_content(response.choices[0].message.content or "{}")


def _summary_from_content(content: str) -> tuple[str, str]:
    payload = json.loads(content or "{}")
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
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return description, ",".join(tags[:10])


def _create_chat_completion(text: str):
    from openai import OpenAI

    return OpenAI(api_key=settings.OPENAI_API_KEY).chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text[:LLM_TEXT_LIMIT]},
        ],
    )


def _complete_summary(text: str):
    """429·503이면 30초, 60초, 120초를 두고 다시 요청합니다."""
    return _call_with_retry(lambda: _create_chat_completion(text))


def _call_with_retry(fn):
    for delay in (*_RETRY_DELAYS, None):
        try:
            return fn()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status not in (429, 503) or delay is None:
                raise
            logger.warning("document index retry status=%s sleep=%s", status, delay)
            time.sleep(delay)


def _require_openai_key() -> None:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("언어 모델 키가 없습니다.")


def _prepare_vision_image(path: str, mime: str) -> tuple[str, str]:
    """언어 모델에 보낼 이미지를 JPEG로 줄입니다."""
    from PIL import Image

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((_MAX_VISION_EDGE, _MAX_VISION_EDGE))
            handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            handle.close()
            image.save(handle.name, "JPEG", quality=85)
            return handle.name, "image/jpeg"
    except Exception:
        logger.warning("vision image normalize failed path=%s", path)
        if mime in _VISION_MIMES:
            return path, mime
        raise


def _create_vision_completion(path: str, mime: str):
    from openai import OpenAI

    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return OpenAI(api_key=settings.OPENAI_API_KEY).chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _IMAGE_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    {"type": "text", "text": "이 이미지를 분석하여 검색 색인을 만들어 주세요."},
                ],
            },
        ],
    )


def _describe_image(path: str, mime: str) -> tuple[str, str]:
    """이미지 설명과 쉼표 구분 태그를 만듭니다."""
    _require_openai_key()
    prepared, prepared_mime = _prepare_vision_image(path, mime)
    try:
        response = _call_with_retry(lambda: _create_vision_completion(prepared, prepared_mime))
    finally:
        if prepared != path and os.path.exists(prepared):
            os.remove(prepared)
    return _summary_from_content(response.choices[0].message.content or "{}")


def _image_mime(content_type: str, filename: str) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in _VISION_MIMES:
        return mime
    ext = os.path.splitext(filename or "")[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


def _extract_audio_sample(audio_path: str, max_seconds: int = _AUDIO_SAMPLE_SECONDS) -> str:
    """앞부분을 16kHz 모노 mp3로 잘라 임시 경로를 반환합니다."""
    handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    handle.close()
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                audio_path,
                "-t",
                str(max_seconds),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-b:a",
                "64k",
                handle.name,
                "-y",
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
    except Exception as exc:
        if os.path.exists(handle.name):
            os.remove(handle.name)
        raise RuntimeError("오디오 샘플을 만들지 못했습니다.") from exc
    return handle.name


def _transcribe_with_whisper(audio_path: str) -> str:
    from openai import OpenAI

    _require_openai_key()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def _once() -> str:
        with open(audio_path, "rb") as handle:
            result = client.audio.transcriptions.create(
                model=_WHISPER_MODEL,
                file=handle,
                response_format="text",
            )
        return result if isinstance(result, str) else str(result)

    return _call_with_retry(_once)


def _extract_video_frames(video_path: str, num_frames: int = _VIDEO_FRAME_COUNT) -> list[str]:
    """영상에서 균등 간격의 JPEG 프레임 경로를 반환합니다."""
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        duration = float(probe.stdout.strip())
    except Exception as exc:
        raise RuntimeError("영상 길이를 읽지 못했습니다.") from exc

    frame_paths: list[str] = []
    for index in range(num_frames):
        timestamp = duration * (index + 1) / (num_frames + 1)
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.close()
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss",
                    str(timestamp),
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    handle.name,
                    "-y",
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
            frame_paths.append(handle.name)
        except Exception:
            if os.path.exists(handle.name):
                os.remove(handle.name)
            logger.warning("video frame extract failed timestamp=%s", timestamp)
    if not frame_paths:
        raise RuntimeError("영상에서 장면을 추출하지 못했습니다.")
    return frame_paths


def _remove_files(paths: list[str]) -> None:
    for path in paths:
        if path and os.path.exists(path):
            os.remove(path)


def _index_media(path: str, kind: str, content_type: str, filename: str) -> tuple[str, str, str]:
    """미디어 파일의 추출 본문, 설명, 태그를 만듭니다."""
    if kind == "image":
        description, tags = _describe_image(path, _image_mime(content_type, filename))
        return description[:EXTRACTED_TEXT_LIMIT], description, tags
    if kind == "audio":
        sample = _extract_audio_sample(path)
        try:
            transcript = _transcribe_with_whisper(sample).strip()
        finally:
            if sample != path:
                _remove_files([sample])
        if len(transcript) < MIN_LLM_CHARS:
            return transcript[:EXTRACTED_TEXT_LIMIT], transcript[:300], ""
        description, tags = summarize(transcript[:LLM_TEXT_LIMIT])
        return transcript[:EXTRACTED_TEXT_LIMIT], description, tags
    frames = _extract_video_frames(path)
    try:
        descriptions: list[str] = []
        tag_groups: list[str] = []
        for position, frame in enumerate(frames):
            description, tags = _describe_image(frame, "image/jpeg")
            if description:
                descriptions.append(description)
            if tags:
                tag_groups.append(tags)
            if position < len(frames) - 1:
                time.sleep(DEFAULT_INDEX_SLEEP_SECONDS)
    finally:
        _remove_files(frames)
    merged = _summary_from_content(
        json.dumps(
            {
                "description_ko": descriptions[0] if descriptions else "",
                "tags_ko": [tag for group in tag_groups for tag in group.split(",") if tag],
            },
            ensure_ascii=False,
        )
    )
    return "\n".join(descriptions)[:EXTRACTED_TEXT_LIMIT], merged[0], merged[1]


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
        kind = media_kind(file.content_type, file.original_filename)
        personal = file.folder.space.kind == DocumentSpace.Kind.PERSONAL
        if kind:
            if personal:
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
            try:
                extracted, description, tags = _index_media(
                    path,
                    kind,
                    file.content_type,
                    file.original_filename,
                )
            except Exception:
                logger.exception("document media index failed file_id=%s", file_id)
                _save_index(
                    index,
                    extracted_text="",
                    description="",
                    tags="",
                    source=DocumentIndex.Source.LLM,
                    status=DocumentIndex.Status.FAILED,
                    error="색인에 실패했습니다.",
                )
                return
            _save_index(
                index,
                extracted_text=extracted,
                description=description,
                tags=tags,
                source=DocumentIndex.Source.LLM,
                status=DocumentIndex.Status.READY,
                error="",
            )
            return
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


@dataclass
class IndexBatchResult:
    ready: int = 0
    failed: int = 0
    skipped: int = 0
    passed: int = 0


def _skipped_media_q() -> Q:
    """이전에 제외된 이미지, 오디오, 영상을 다시 색인 대상에 넣습니다."""
    mime = (
        Q(content_type__istartswith="image/")
        | Q(content_type__istartswith="audio/")
        | Q(content_type__istartswith="video/")
    )
    names = Q()
    for ext in _IMAGE_EXTENSIONS | _AUDIO_EXTENSIONS | _VIDEO_EXTENSIONS:
        names |= Q(original_filename__iendswith=ext)
    return Q(index__index_status=DocumentIndex.Status.SKIPPED) & (mime | names)


def pending_shared_file_ids(*, limit: int | None = None) -> list[int]:
    """언어 모델 색인이 아직 없는 공유 파일 id를 반환합니다."""
    cutoff = timezone.now() - STALE_PROCESSING
    queryset = (
        DocumentFile.objects.filter(folder__space__kind=DocumentSpace.Kind.SHARED)
        .filter(
            Q(index__isnull=True)
            | Q(
                index__index_status__in=[
                    DocumentIndex.Status.PENDING,
                    DocumentIndex.Status.FAILED,
                ]
            )
            | Q(
                index__index_status=DocumentIndex.Status.PROCESSING,
                index__updated_at__lt=cutoff,
            )
            | _skipped_media_q()
        )
        .order_by("id")
        .values_list("id", flat=True)
        .distinct()
    )
    if limit is not None:
        queryset = queryset[:limit]
    return list(queryset)


def split_shared_file_ids(file_ids: list[int]) -> tuple[list[int], int]:
    """공유 문서 id와 개인 문서 건수를 나눕니다."""
    files = DocumentFile.objects.filter(id__in=file_ids).select_related("folder__space")
    kinds = {file.id: file.folder.space.kind for file in files}
    shared: list[int] = []
    personal = 0
    for file_id in file_ids:
        kind = kinds.get(file_id)
        if kind == DocumentSpace.Kind.SHARED:
            shared.append(file_id)
        elif kind == DocumentSpace.Kind.PERSONAL:
            personal += 1
    return shared, personal


def index_files(
    file_ids: list[int],
    sleep_seconds: float,
    *,
    force: bool = False,
    on_item: Callable[[int, str, str], None] | None = None,
) -> IndexBatchResult:
    """문서를 한 건씩 색인합니다. 언어 모델을 호출한 파일 사이에만 대기합니다."""
    result = IndexBatchResult()
    total = len(file_ids)
    for position, file_id in enumerate(file_ids):
        filename = (
            DocumentFile.objects.filter(id=file_id)
            .values_list("original_filename", flat=True)
            .first()
            or ""
        )
        if not _claim_file(file_id, force=force):
            result.passed += 1
            _notify(on_item, file_id, filename, "passed")
            continue
        build_index(file_id)
        row = (
            DocumentIndex.objects.filter(file_id=file_id)
            .values_list("index_status", "index_source")
            .first()
        )
        status = row[0] if row else DocumentIndex.Status.FAILED
        source = row[1] if row else ""
        outcome = _count_outcome(result, status)
        _notify(on_item, file_id, filename, outcome)
        if source == DocumentIndex.Source.LLM and sleep_seconds > 0 and position < total - 1:
            time.sleep(sleep_seconds)
    return result


def run_index_files(
    file_ids: list[int],
    sleep_seconds: float,
    *,
    force: bool = False,
) -> IndexBatchResult:
    close_old_connections()
    try:
        return index_files(file_ids, sleep_seconds, force=force)
    finally:
        connections.close_all()


def _claim_file(file_id: int, *, force: bool) -> bool:
    file = DocumentFile.objects.filter(id=file_id).only("id", "original_filename").first()
    if file is None:
        return False
    cutoff = timezone.now() - STALE_PROCESSING
    statuses = [
        DocumentIndex.Status.PENDING,
        DocumentIndex.Status.FAILED,
        DocumentIndex.Status.SKIPPED,
    ]
    if force:
        statuses.extend([DocumentIndex.Status.READY, DocumentIndex.Status.SKIPPED])
    claimed = (
        DocumentIndex.all_objects.filter(file_id=file_id)
        .filter(
            Q(index_status__in=statuses)
            | Q(index_status=DocumentIndex.Status.PROCESSING, updated_at__lt=cutoff)
            | Q(deleted_at__isnull=False)
        )
        .update(
            index_status=DocumentIndex.Status.PROCESSING,
            error="",
            deleted_at=None,
            filename=file.original_filename,
            updated_at=timezone.now(),
        )
    )
    if claimed:
        return True
    if DocumentIndex.all_objects.filter(file_id=file_id).exists():
        return False
    try:
        DocumentIndex.objects.create(
            file=file,
            filename=file.original_filename,
            index_status=DocumentIndex.Status.PROCESSING,
            error="",
        )
    except IntegrityError:
        return False
    return True


def _count_outcome(result: IndexBatchResult, status: str) -> str:
    if status == DocumentIndex.Status.READY:
        result.ready += 1
        return "ready"
    if status == DocumentIndex.Status.FAILED:
        result.failed += 1
        return "failed"
    if status == DocumentIndex.Status.SKIPPED:
        result.skipped += 1
        return "skipped"
    result.passed += 1
    return status or "passed"


def _notify(
    on_item: Callable[[int, str, str], None] | None,
    file_id: int,
    filename: str,
    outcome: str,
) -> None:
    if on_item is not None:
        on_item(file_id, filename, outcome)
