import mimetypes
import os
import unicodedata
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from config.aws import get_s3_client
from document.indexer import build_index
from document.models import DocumentFile, DocumentFolder, DocumentIndex
from document.storage import build_object_key
from document.utils import _ensure_root, _ensure_shared, _root_folder
from workspace.models import Workspace, WorkspaceMember

User = get_user_model()

_MAX_SIZE = 2_147_483_647
_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_EXTRA_TYPES = {
    ".hwp": "application/x-hwp",
    ".hwpx": "application/vnd.hancom.hwpx",
    ".ai": "application/postscript",
    ".eml": "message/rfc822",
    ".psb": "application/vnd.adobe.photoshop",
}


@dataclass
class ImportResult:
    imported: int = 0
    indexed: int = 0
    removed: int = 0
    skipped_existing: int = 0
    skipped: int = 0
    folders_created: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class _PlannedFolder:
    """미리보기에서 아직 만들지 않은 폴더입니다."""


def import_backup_documents(
    *,
    workspace: Workspace,
    user,
    prefix: str = "backup/",
    dry_run: bool = False,
    index: bool = False,
    limit: int | None = None,
    client=None,
    bucket: str | None = None,
) -> ImportResult:
    """S3 prefix 안의 파일을 꺼내 공유 문서함 루트에 복원합니다.

    prefix 이름 자체는 문서함 폴더로 만들지 않습니다. 등록에 성공하면 원본 객체는 지웁니다.
    같은 폴더에 같은 이름과 크기가 있으면 다시 복사하지 않고 원본만 지웁니다.
    """
    result = ImportResult()
    source_prefix = _normalize_prefix(prefix)
    storage = client if client is not None else get_s3_client()
    bucket_name = bucket if bucket is not None else (getattr(settings, "AWS_UPLOAD_BUCKET", "") or "")
    if not bucket_name:
        raise RuntimeError("문서 저장소가 설정되지 않았습니다.")

    space = _ensure_shared(workspace, user)
    _ensure_root(space, user)
    root = _root_folder(space)
    cache: dict[tuple[str, ...], DocumentFolder | _PlannedFolder] = {}

    for key, size in _iter_objects(storage, bucket_name, source_prefix):
        if limit is not None and result.imported >= limit:
            break
        relative = key[len(source_prefix):]
        if not relative or relative.endswith("/"):
            continue
        parts = _split_key(relative)
        if parts is None:
            result.skipped += 1
            result.errors.append(f"경로를 폴더로 나눌 수 없습니다: {relative}")
            continue
        filename = parts[-1]
        folder_names = parts[:-1]
        if _is_skipped_name(relative, filename):
            result.skipped += 1
            continue
        if size < 1 or size > _MAX_SIZE:
            result.skipped += 1
            result.errors.append(f"크기를 등록할 수 없습니다 ({size}): {relative}")
            continue

        folder = _ensure_folders(
            space, root, folder_names, user, dry_run, cache, result
        )
        existing = _existing_file(folder, filename)
        if existing is not None:
            if not dry_run and _same_restored_file(existing, key, size):
                _take_out(storage, bucket_name, key, relative, result)
            elif existing.size != size:
                result.errors.append(f"같은 이름의 다른 파일이 있습니다: {relative}")
            if index and not dry_run and _needs_index(existing):
                _index_document(existing, result)
            else:
                result.skipped_existing += 1
            continue

        if dry_run:
            result.imported += 1
            continue

        dest_key = build_object_key(workspace.id, filename)
        try:
            storage.copy_object(
                Bucket=bucket_name,
                Key=dest_key,
                CopySource={"Bucket": bucket_name, "Key": key},
            )
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"복사 실패: {relative} ({exc})")
            continue

        try:
            with transaction.atomic():
                document = DocumentFile.objects.create(
                    folder=folder,
                    original_filename=filename,
                    object_key=dest_key,
                    content_type=_content_type(filename),
                    size=size,
                    uploaded_by=user,
                )
                DocumentIndex.objects.create(
                    file=document,
                    filename=filename,
                    index_status=DocumentIndex.Status.PENDING,
                    index_source=DocumentIndex.Source.LOCAL,
                )
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"등록 실패: {relative} ({exc})")
            _delete_quiet(storage, bucket_name, dest_key)
            continue

        result.imported += 1
        _take_out(storage, bucket_name, key, relative, result)
        if index:
            _index_document(document, result)

    return result


def resolve_workspace(workspace_id: int | None, workspace_slug: str) -> Workspace:
    if workspace_id is not None:
        workspace = Workspace.objects.filter(id=workspace_id).first()
    else:
        workspace = Workspace.objects.filter(slug=workspace_slug).first()
    if workspace is None:
        target = workspace_id if workspace_id is not None else workspace_slug
        raise RuntimeError(f"워크스페이스를 찾을 수 없습니다: {target}")
    return workspace


def resolve_user(workspace: Workspace, user_id: int | None):
    if user_id is not None:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise RuntimeError(f"사용자를 찾을 수 없습니다: {user_id}")
        return user
    owner = (
        WorkspaceMember.objects.filter(
            workspace=workspace,
            role=WorkspaceMember.Role.OWNER,
        )
        .select_related("user")
        .order_by("id")
        .first()
    )
    if owner is None:
        return None
    return owner.user


def _normalize_prefix(prefix: str) -> str:
    cleaned = (prefix or "backup/").strip().lstrip("/")
    if cleaned and not cleaned.endswith("/"):
        cleaned = f"{cleaned}/"
    return cleaned


def _iter_objects(client, bucket: str, prefix: str):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], int(obj["Size"])


def _split_key(relative: str) -> list[str] | None:
    parts = []
    for raw in relative.split("/"):
        if raw == "":
            continue
        cleaned = unicodedata.normalize("NFC", raw).strip()
        if not cleaned or cleaned in {".", ".."} or len(cleaned) > 255:
            return None
        parts.append(cleaned)
    if not parts:
        return None
    return parts


def _is_skipped_name(relative: str, filename: str) -> bool:
    if relative == "db.json":
        return True
    lowered = filename.lower()
    if lowered in _JUNK_NAMES or filename.startswith("._") or filename.startswith("."):
        return True
    return False


def _content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    guessed = _EXTRA_TYPES.get(ext)
    if guessed is None:
        guessed, _encoding = mimetypes.guess_type(filename)
    cleaned = (guessed or "application/octet-stream").split(";", 1)[0].strip().lower()
    return cleaned[:100] or "application/octet-stream"


def _ensure_folders(space, root, names, user, dry_run, cache, result):
    parent = root
    built: list[str] = []
    for name in names:
        built.append(name)
        key = tuple(built)
        cached = cache.get(key)
        if cached is not None:
            parent = cached
            continue
        found = None
        if isinstance(parent, DocumentFolder):
            found = DocumentFolder.objects.filter(
                space=space,
                parent=parent,
                name=name,
                is_root=False,
            ).first()
        if found is not None:
            cache[key] = found
            parent = found
            continue
        if dry_run or not isinstance(parent, DocumentFolder):
            planned = _PlannedFolder()
            cache[key] = planned
            result.folders_created += 1
            parent = planned
            continue
        try:
            folder = DocumentFolder.objects.create(
                space=space,
                parent=parent,
                name=name,
                is_root=False,
                created_by=user,
            )
        except IntegrityError:
            folder = DocumentFolder.objects.get(
                space=space,
                parent=parent,
                name=name,
                is_root=False,
            )
        else:
            result.folders_created += 1
        cache[key] = folder
        parent = folder
    return parent


def _existing_file(folder, filename: str) -> DocumentFile | None:
    if not isinstance(folder, DocumentFolder):
        return None
    return (
        DocumentFile.objects.select_related("index")
        .filter(folder=folder, original_filename=filename)
        .first()
    )


def _index_document(document: DocumentFile, result: ImportResult) -> None:
    build_index(document.id)
    status = (
        DocumentIndex.objects.filter(file=document)
        .values_list("index_status", flat=True)
        .first()
    )
    if status == DocumentIndex.Status.FAILED:
        result.errors.append(f"색인 실패: {document.original_filename}")
        return
    result.indexed += 1


def _needs_index(document: DocumentFile) -> bool:
    try:
        index = document.index
    except DocumentIndex.DoesNotExist:
        return True
    return index.index_status in {
        DocumentIndex.Status.PENDING,
        DocumentIndex.Status.FAILED,
    }


def _same_restored_file(document: DocumentFile, key: str, size: int) -> bool:
    return document.object_key != key and document.size == size


def _take_out(client, bucket: str, key: str, relative: str, result: ImportResult) -> None:
    if _delete_quiet(client, bucket, key):
        result.removed += 1
        return
    result.errors.append(f"원본 삭제 실패: {relative}")


def _delete_quiet(client, bucket: str, key: str) -> bool:
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    return True
