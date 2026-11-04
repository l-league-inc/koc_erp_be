import os
import re
import tempfile

from django.conf import settings
from ninja.errors import HttpError

from config.aws import get_s3_client

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
PRESIGN_EXPIRES = 300

_FILENAME_SAFE = re.compile(r"[^0-9A-Za-z._\-\uac00-\ud7a3]")


def document_prefix(workspace_id: int) -> str:
    return (
        f"{settings.SERVICE_NAME.lower()}/documents/"
        f"{settings.DJANGO_ENV_NAME}/{workspace_id}/"
    )


def display_filename(file_name: str) -> str:
    base = os.path.basename((file_name or "").replace("\\", "/")).strip()
    if not base or base in {".", ".."}:
        raise HttpError(400, "파일 이름이 필요합니다.")
    if len(base) > 255:
        raise HttpError(400, "파일 이름은 255자를 넘길 수 없습니다.")
    return base


def safe_filename(file_name: str) -> str:
    base = display_filename(file_name).replace(" ", "_")
    cleaned = _FILENAME_SAFE.sub("_", base).strip("._") or "file"
    return cleaned[:180]


def build_object_key(workspace_id: int, file_name: str) -> str:
    import uuid

    return f"{document_prefix(workspace_id)}{uuid.uuid4().hex}/{safe_filename(file_name)}"


def assert_object_key(workspace_id: int, object_key: str) -> None:
    prefix = document_prefix(workspace_id)
    if not object_key or not object_key.startswith(prefix) or ".." in object_key:
        raise HttpError(400, "문서 저장 경로가 올바르지 않습니다.")


def assert_size(size: int) -> None:
    if size < 1 or size > MAX_DOCUMENT_BYTES:
        raise HttpError(400, "파일 크기는 1바이트 이상 50MB 이하여야 합니다.")


def clean_content_type(value: str) -> str:
    cleaned = (value or "application/octet-stream").split(";", 1)[0].strip().lower()
    if not cleaned or len(cleaned) > 100 or " " in cleaned:
        raise HttpError(400, "콘텐츠 타입이 올바르지 않습니다.")
    return cleaned


def _bucket() -> str:
    bucket = getattr(settings, "AWS_UPLOAD_BUCKET", "") or ""
    if not bucket:
        raise HttpError(503, "문서 저장소가 설정되지 않았습니다.")
    return bucket


def presign_put(object_key: str, content_type: str) -> str:
    try:
        return get_s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": _bucket(),
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=PRESIGN_EXPIRES,
        )
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "저장소 URL을 만들지 못했습니다.") from None


def presign_get(object_key: str, filename: str) -> str:
    from urllib.parse import quote

    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    disposition = f"attachment; filename*=UTF-8''{quote(safe)}"
    try:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": _bucket(),
                "Key": object_key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=PRESIGN_EXPIRES,
        )
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "저장소 URL을 만들지 못했습니다.") from None


def download_to_temp(object_key: str, suffix: str) -> str:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix[:16])
    path = handle.name
    handle.close()
    try:
        get_s3_client().download_file(_bucket(), object_key, path)
    except HttpError:
        if os.path.exists(path):
            os.remove(path)
        raise
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path
