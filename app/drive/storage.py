import hashlib
import re

from django.conf import settings
from ninja.errors import HttpError

from config.aws import get_s3_client

MAX_RELEASE_BYTES = 200 * 1024 * 1024
PRESIGN_EXPIRES = 900
_VERSION = re.compile(r"^(0|[1-9]\d{0,3})(\.(0|[1-9]\d{0,3})){1,3}$")


def clean_version(value: str) -> str:
    version = (value or "").strip()
    if not _VERSION.fullmatch(version):
        raise ValueError("버전은 1.2.0 형식이어야 합니다.")
    return version


def release_object_key(version: str) -> str:
    env = getattr(settings, "DJANGO_ENV_NAME", "local") or "local"
    return f"koc/drive/{env}/{version}/KOC-ERP.exe"


def presign_release(object_key: str, filename: str = "") -> str:
    try:
        bucket = _bucket()
    except ValueError as exc:
        raise HttpError(503, str(exc)) from None
    params = {"Bucket": bucket, "Key": object_key}
    if filename:
        from urllib.parse import quote

        safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
        params["ResponseContentDisposition"] = f"attachment; filename*=UTF-8''{quote(safe)}"
    try:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=PRESIGN_EXPIRES,
        )
    except HttpError:
        raise
    except Exception:
        raise HttpError(503, "업데이트 주소를 만들지 못했습니다.") from None


def delete_release_object(object_key: str) -> None:
    bucket = _bucket()
    try:
        get_s3_client().delete_object(Bucket=bucket, Key=object_key)
    except ValueError:
        raise
    except Exception:
        raise ValueError("설치 파일을 지우지 못했습니다.") from None


def upload_release(object_key: str, package) -> None:
    bucket = _bucket()
    try:
        package.seek(0)
        get_s3_client().upload_fileobj(
            package,
            bucket,
            object_key,
            ExtraArgs={"ContentType": "application/vnd.microsoft.portable-executable"},
        )
    except HttpError:
        raise
    except Exception:
        raise ValueError("설치 파일을 저장하지 못했습니다.") from None


def hash_package(package) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = package.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_RELEASE_BYTES:
            raise ValueError("설치 파일은 200MB를 넘길 수 없습니다.")
        digest.update(chunk)
    if size < 2:
        raise ValueError("설치 파일이 비어 있습니다.")
    package.seek(0)
    return digest.hexdigest(), size


def _bucket() -> str:
    bucket = getattr(settings, "AWS_UPLOAD_BUCKET", "") or ""
    if not bucket:
        raise ValueError("업데이트 저장소가 설정되지 않았습니다.")
    return bucket
