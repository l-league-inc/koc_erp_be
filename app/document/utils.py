import threading

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import IntegrityError, transaction
from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Coalesce
from ninja.errors import HttpError

from document.indexer import run_index
from document.models import (
    DocumentChange,
    DocumentDownload,
    DocumentFile,
    DocumentFolder,
    DocumentIndex,
    DocumentMailLog,
    DocumentSpace,
)
from document.names import is_windows_name
from document.storage import (
    PRESIGN_EXPIRES,
    assert_object_key,
    assert_size,
    build_object_key,
    clean_content_hash,
    clean_content_type,
    display_filename,
    presign_get,
    presign_put,
)
from workspace.models import WorkspaceMember
from workspace.utils import MCP_CLIENT_HEADER, get_membership

_MANAGE_ROLES = {WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN}


def client_source(request) -> str:
    if request.headers.get(MCP_CLIENT_HEADER) == DocumentDownload.Source.MCP:
        return DocumentDownload.Source.MCP
    return DocumentDownload.Source.USER


def ensure_spaces(user, workspace_id: int) -> list[dict]:
    membership = get_membership(user, workspace_id)
    shared = _ensure_shared(membership.workspace, user)
    personal = _ensure_personal(membership.workspace, user)
    return [serialize_space(shared), serialize_space(personal)]


def list_folders(user, workspace_id: int, space_id: int, parent_id: int | None) -> list[dict]:
    _membership, space = _get_space(user, workspace_id, space_id)
    if parent_id is None:
        parent = _root_folder(space)
    else:
        parent = _folder_in_space(space, parent_id)
    folders = list(DocumentFolder.objects.filter(parent=parent).order_by("name", "id"))
    paths = ancestor_paths(folders)
    return [serialize_folder(folder, path=paths[folder.id]) for folder in folders]


def create_folder(user, workspace_id: int, parent_id: int, name: str) -> dict:
    _membership, parent = _get_folder(user, workspace_id, parent_id)
    cleaned = _clean_folder_name(name)
    if DocumentFolder.objects.filter(parent=parent, name=cleaned).exists():
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.")
    try:
        folder = DocumentFolder.objects.create(
            space=parent.space,
            parent=parent,
            name=cleaned,
            is_root=False,
            created_by=user,
        )
    except IntegrityError:
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.") from None
    _record_folder(folder, DocumentChange.Op.UPSERT)
    return serialize_folder(folder)


def update_folder(user, workspace_id: int, folder_id: int, data: dict) -> dict:
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    if folder.is_root:
        raise HttpError(400, "최상위 폴더는 바꿀 수 없습니다.")
    parent = folder.parent
    if "parent_id" in data:
        _membership, parent = _get_folder(user, workspace_id, int(data["parent_id"]))
        if parent.space_id != folder.space_id:
            raise HttpError(400, "다른 문서함으로는 옮길 수 없습니다.")
        if _is_descendant(folder, parent):
            raise HttpError(400, "폴더를 그 하위 폴더로 옮길 수 없습니다.")
    name = _clean_folder_name(data.get("name", folder.name))
    if (
        DocumentFolder.objects.filter(space_id=folder.space_id, parent=parent, name=name)
        .exclude(id=folder.id)
        .exists()
    ):
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.")
    folder.name = name
    folder.parent = parent
    try:
        folder.save(update_fields=["name", "parent", "updated_at"])
    except IntegrityError:
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.") from None
    _record_folder(folder, DocumentChange.Op.UPSERT)
    return serialize_folder(folder)


def delete_folder(user, workspace_id: int, folder_id: int) -> None:
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    if folder.is_root:
        raise HttpError(400, "최상위 폴더는 지울 수 없습니다.")
    if DocumentFolder.objects.filter(parent=folder).exists():
        raise HttpError(400, "하위 폴더가 있는 폴더는 지울 수 없습니다.")
    if DocumentFile.objects.filter(folder=folder).exists():
        raise HttpError(400, "파일이 있는 폴더는 지울 수 없습니다.")
    _record_folder(folder, DocumentChange.Op.DELETE)
    folder.delete()


def create_upload(
    user,
    workspace_id: int,
    folder_id: int,
    file_name: str,
    content_type: str,
    size: int,
) -> dict:
    _get_folder(user, workspace_id, folder_id)
    assert_size(size)
    cleaned_type = clean_content_type(content_type)
    display_filename(file_name)
    object_key = build_object_key(workspace_id, file_name)
    return {
        "upload_url": presign_put(object_key, cleaned_type),
        "object_key": object_key,
        "content_type": cleaned_type,
        "expires_in": PRESIGN_EXPIRES,
    }


@transaction.atomic
def create_file(user, workspace_id: int, data: dict) -> dict:
    _membership, folder = _get_folder(user, workspace_id, int(data["folder_id"]))
    assert_size(int(data["size"]))
    object_key = str(data["object_key"])
    assert_object_key(workspace_id, object_key)
    if DocumentFile.objects.filter(object_key=object_key).exists():
        raise HttpError(400, "이미 등록된 문서입니다.")
    filename = display_filename(str(data["original_filename"]))
    content_type = clean_content_type(str(data["content_type"]))
    content_hash = clean_content_hash(data.get("content_hash"))
    if _file_name_taken(folder, filename):
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.")
    try:
        file = DocumentFile.objects.create(
            folder=folder,
            original_filename=filename,
            object_key=object_key,
            content_type=content_type,
            size=int(data["size"]),
            content_hash=content_hash,
            uploaded_by=user,
        )
    except IntegrityError:
        raise HttpError(400, "이미 등록된 문서이거나 같은 이름이 있습니다.") from None
    DocumentIndex.objects.create(
        file=file,
        filename=filename,
        index_status=DocumentIndex.Status.PENDING,
        index_source=DocumentIndex.Source.LOCAL,
    )
    schedule_index(file.id)
    _record_file(file, DocumentChange.Op.UPSERT)
    return serialize_file(file, detail=True)


def list_files(user, workspace_id: int, folder_id: int) -> list[dict]:
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    files = list(
        DocumentFile.objects.filter(folder=folder)
        .select_related("folder__space", "index", "uploaded_by")
        .order_by("-created_at", "-id")
    )
    paths = ancestor_paths([file.folder for file in files])
    return [serialize_file(file, detail=False, path=paths[file.folder_id]) for file in files]


def get_file_detail(user, workspace_id: int, file_id: int) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    return serialize_file(file, detail=True)


def update_file(user, workspace_id: int, file_id: int, data: dict) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    folder = file.folder
    if data.get("folder_id") is not None:
        _membership, folder = _get_folder(user, workspace_id, int(data["folder_id"]))
        if folder.space_id != file.folder.space_id:
            raise HttpError(400, "다른 문서함으로는 옮길 수 없습니다.")
    filename = file.original_filename
    if data.get("original_filename") is not None:
        filename = display_filename(str(data["original_filename"]))
    if folder.id == file.folder_id and filename == file.original_filename:
        return serialize_file(file, detail=False)
    if _file_name_taken(folder, filename, exclude_id=file.id):
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.")
    file.folder = folder
    file.original_filename = filename
    try:
        file.save(update_fields=["folder", "original_filename", "updated_at"])
    except IntegrityError:
        raise HttpError(400, "같은 폴더에 같은 이름이 있습니다.") from None
    index = _index_of(file)
    if index is not None and index.filename != filename:
        index.filename = filename
        index.save(update_fields=["filename", "updated_at"])
    _record_file(file, DocumentChange.Op.UPSERT)
    return serialize_file(file, detail=False)


def delete_file(user, workspace_id: int, file_id: int) -> None:
    membership, file = _get_file(user, workspace_id, file_id)
    if file.uploaded_by_id != user.id and membership.role not in _MANAGE_ROLES:
        raise HttpError(403, "문서를 지울 권한이 없습니다.")
    _record_file(file, DocumentChange.Op.DELETE)
    file.delete()


def search_files(user, workspace_id: int, keyword: str) -> list[dict]:
    get_membership(user, workspace_id)
    query_text = (keyword or "").strip()
    if not query_text:
        raise HttpError(400, "검색어가 필요합니다.")
    if len(query_text) > 200:
        raise HttpError(400, "검색어는 200자를 넘길 수 없습니다.")
    search_query = SearchQuery(query_text, config="simple")
    visible = Q(file__folder__space__kind=DocumentSpace.Kind.SHARED) | Q(
        file__folder__space__kind=DocumentSpace.Kind.PERSONAL,
        file__folder__space__owner=user,
    )
    rows = (
        DocumentIndex.objects.select_related("file__folder__space")
        .filter(file__folder__space__workspace_id=workspace_id)
        .filter(visible)
        .annotate(
            rank=Coalesce(
                SearchRank(F("search_vector"), search_query),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        .filter(
            Q(rank__gt=0)
            | Q(file__original_filename__icontains=query_text)
            | Q(description_ko__icontains=query_text)
            | Q(extracted_text__icontains=query_text)
        )
        .order_by("-rank", "-file__created_at", "-file_id")[:20]
    )
    indexes = list(rows)
    paths = ancestor_paths([index.file.folder for index in indexes])
    hits = []
    for index in indexes:
        score = float(index.rank or 0)
        if score <= 0:
            score = 0.01
        hits.append(
            {
                "id": index.file_id,
                "original_filename": index.file.original_filename,
                "folder_id": index.file.folder_id,
                "folder_path": paths[index.file.folder_id],
                "description_ko": index.description_ko,
                "score": score,
            }
        )
    return hits


def create_replace_upload(
    user,
    workspace_id: int,
    file_id: int,
    content_type: str,
    size: int,
    base_hash: str,
) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    _require_base_hash(file, base_hash)
    assert_size(size)
    cleaned_type = clean_content_type(content_type)
    object_key = build_object_key(workspace_id, file.original_filename)
    return {
        "upload_url": presign_put(object_key, cleaned_type),
        "object_key": object_key,
        "content_type": cleaned_type,
        "expires_in": PRESIGN_EXPIRES,
    }


@transaction.atomic
def replace_file_content(user, workspace_id: int, file_id: int, data: dict) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    _require_base_hash(file, str(data.get("base_hash") or ""))
    assert_size(int(data["size"]))
    object_key = str(data["object_key"])
    assert_object_key(workspace_id, object_key)
    if DocumentFile.objects.filter(object_key=object_key).exclude(id=file.id).exists():
        raise HttpError(400, "이미 등록된 문서입니다.")
    file.object_key = object_key
    file.content_type = clean_content_type(str(data["content_type"]))
    file.size = int(data["size"])
    file.content_hash = clean_content_hash(data.get("content_hash"), required=True)
    try:
        file.save(
            update_fields=["object_key", "content_type", "size", "content_hash", "updated_at"]
        )
    except IntegrityError:
        raise HttpError(400, "이미 등록된 문서입니다.") from None
    _reset_index(file)
    _record_file(file, DocumentChange.Op.UPSERT)
    return serialize_file(file, detail=True)


def create_sync_url(user, workspace_id: int, file_id: int) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    return {
        "url": presign_get(file.object_key, file.original_filename),
        "expires_in": PRESIGN_EXPIRES,
    }


def sync_cursor(user, workspace_id: int, space_id: int) -> dict:
    _membership, space = _get_space(user, workspace_id, space_id)
    latest = (
        DocumentChange.objects.filter(space=space)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    return {"cursor": int(latest or 0)}


def list_changes(user, workspace_id: int, space_id: int, cursor: int) -> dict:
    _membership, space = _get_space(user, workspace_id, space_id)
    if cursor < 0:
        raise HttpError(400, "커서가 올바르지 않습니다.")
    rows = list(
        DocumentChange.objects.filter(space=space, id__gt=cursor).order_by("id")[:200]
    )
    next_cursor = rows[-1].id if rows else cursor
    return {
        "changes": [_serialize_change(row) for row in rows],
        "next_cursor": next_cursor,
    }


def create_download(user, workspace_id: int, file_id: int, source: str) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    url = presign_get(file.object_key, file.original_filename)
    DocumentDownload.objects.create(file=file, user=user, source=source)
    return {"url": url, "expires_in": PRESIGN_EXPIRES}


def list_mail_logs(user, workspace_id: int, file_id: int) -> list[dict]:
    _membership, file = _get_file(user, workspace_id, file_id)
    logs = file.mail_logs.select_related("sender").order_by("-created_at", "-id")
    return [serialize_mail_log(log) for log in logs]


def reindex_file(user, workspace_id: int, file_id: int) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    if file.uploaded_by_id != user.id:
        raise HttpError(403, "올린 사람만 색인을 다시 실행할 수 있습니다.")
    index = _index_of(file)
    if index is None:
        index = DocumentIndex.objects.create(
            file=file,
            filename=file.original_filename,
            index_status=DocumentIndex.Status.PENDING,
        )
    else:
        index.index_status = DocumentIndex.Status.PENDING
        index.error = ""
        index.save(update_fields=["index_status", "error", "updated_at"])
    schedule_index(file.id)
    file.index = index
    return serialize_file(file, detail=True)


def schedule_index(file_id: int) -> None:
    if getattr(settings, "TESTING", False):
        return

    def _start() -> None:
        threading.Thread(target=run_index, args=(file_id,), daemon=True).start()

    transaction.on_commit(_start)


def serialize_space(space: DocumentSpace) -> dict:
    root = _root_folder(space)
    return {
        "id": space.id,
        "workspace_id": space.workspace_id,
        "kind": space.kind,
        "owner_id": space.owner_id,
        "root_folder_id": root.id,
    }


def serialize_folder(folder: DocumentFolder, *, path: str | None = None) -> dict:
    return {
        "id": folder.id,
        "space_id": folder.space_id,
        "parent_id": folder.parent_id,
        "name": folder.name,
        "is_root": folder.is_root,
        "path": folder_path(folder) if path is None else path,
        "created_at": folder.created_at,
    }


def serialize_file(file: DocumentFile, *, detail: bool, path: str | None = None) -> dict:
    folder = file.folder
    space = folder.space
    index = _index_of(file)
    file_path = _file_path(folder, file.original_filename) if path is None else (
        f"{path}/{file.original_filename}" if path else file.original_filename
    )
    payload = {
        "id": file.id,
        "workspace_id": space.workspace_id,
        "space_id": space.id,
        "space_kind": space.kind,
        "folder_id": folder.id,
        "original_filename": file.original_filename,
        "content_type": file.content_type,
        "size": file.size,
        "uploaded_by_id": file.uploaded_by_id,
        "path": file_path,
        "index_status": index.index_status if index else DocumentIndex.Status.PENDING,
        "index_source": index.index_source if index else DocumentIndex.Source.LOCAL,
        "description_ko": index.description_ko if index else "",
        "tags_ko": _tags(index.tags_ko if index else ""),
        "content_hash": file.content_hash,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
    }
    if detail:
        payload["extracted_text"] = index.extracted_text if index else ""
        payload["error"] = index.error if index else ""
    return payload


def serialize_mail_log(log: DocumentMailLog) -> dict:
    return {
        "id": log.id,
        "file_id": log.file_id,
        "sender_id": log.sender_id,
        "recipients": log.recipients or [],
        "subject": log.subject,
        "status": log.status,
        "sent_at": log.sent_at,
        "error": log.error,
        "created_at": log.created_at,
    }


def ancestor_paths(folders: list[DocumentFolder]) -> dict[int, str]:
    """폴더마다 부모를 다시 조회하지 않고 경로를 만듭니다."""
    cache = {folder.id: folder for folder in folders}
    pending = {
        folder.parent_id
        for folder in folders
        if folder.parent_id and folder.parent_id not in cache
    }
    while pending:
        rows = list(DocumentFolder.objects.filter(id__in=pending))
        pending = set()
        for row in rows:
            cache[row.id] = row
            if row.parent_id and row.parent_id not in cache:
                pending.add(row.parent_id)

    def build(folder: DocumentFolder) -> str:
        names: list[str] = []
        seen: set[int] = set()
        current_id = folder.id
        while current_id and current_id not in seen:
            seen.add(current_id)
            current = cache.get(current_id)
            if current is None or current.is_root:
                break
            names.append(current.name)
            current_id = current.parent_id
        names.reverse()
        return "/".join(names)

    return {folder.id: build(folder) for folder in folders}


def folder_path(folder: DocumentFolder) -> str:
    names: list[str] = []
    current = folder
    seen: set[int] = set()
    while current is not None and not current.is_root and current.id not in seen:
        seen.add(current.id)
        names.append(current.name)
        current = current.parent
    names.reverse()
    return "/".join(names)


def _file_path(folder: DocumentFolder, filename: str) -> str:
    path = folder_path(folder)
    if path:
        return f"{path}/{filename}"
    return filename


def _tags(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _clean_folder_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 255 or not is_windows_name(cleaned):
        raise HttpError(400, "폴더 이름이 올바르지 않습니다.")
    return cleaned


def _can_see_space(user, space: DocumentSpace) -> bool:
    if space.kind == DocumentSpace.Kind.SHARED:
        return True
    return space.owner_id == user.id


def _get_space(user, workspace_id: int, space_id: int) -> tuple[WorkspaceMember, DocumentSpace]:
    membership = get_membership(user, workspace_id)
    space = DocumentSpace.objects.filter(id=space_id, workspace_id=workspace_id).first()
    if space is None or not _can_see_space(user, space):
        raise HttpError(404, "문서함을 찾을 수 없습니다.")
    return membership, space


def _get_folder(user, workspace_id: int, folder_id: int) -> tuple[WorkspaceMember, DocumentFolder]:
    membership = get_membership(user, workspace_id)
    folder = (
        DocumentFolder.objects.select_related("space")
        .filter(id=folder_id, space__workspace_id=workspace_id)
        .first()
    )
    if folder is None or not _can_see_space(user, folder.space):
        raise HttpError(404, "폴더를 찾을 수 없습니다.")
    return membership, folder


def _get_file(user, workspace_id: int, file_id: int) -> tuple[WorkspaceMember, DocumentFile]:
    membership = get_membership(user, workspace_id)
    file = (
        DocumentFile.objects.select_related("folder__space", "index")
        .filter(id=file_id, folder__space__workspace_id=workspace_id)
        .first()
    )
    if file is None or not _can_see_space(user, file.folder.space):
        raise HttpError(404, "문서를 찾을 수 없습니다.")
    return membership, file


def _folder_in_space(space: DocumentSpace, folder_id: int) -> DocumentFolder:
    folder = DocumentFolder.objects.filter(id=folder_id, space=space).first()
    if folder is None:
        raise HttpError(404, "폴더를 찾을 수 없습니다.")
    return folder


def _root_folder(space: DocumentSpace) -> DocumentFolder:
    root = DocumentFolder.objects.filter(space=space, is_root=True).first()
    if root is None:
        raise HttpError(404, "문서함을 찾을 수 없습니다.")
    return root


def _ensure_shared(workspace, user) -> DocumentSpace:
    existing = DocumentSpace.objects.filter(
        workspace=workspace,
        kind=DocumentSpace.Kind.SHARED,
    ).first()
    if existing is not None:
        _ensure_root(existing, user)
        return existing
    try:
        with transaction.atomic():
            space = DocumentSpace.objects.create(
                workspace=workspace,
                kind=DocumentSpace.Kind.SHARED,
                owner=None,
            )
            DocumentFolder.objects.create(
                space=space,
                parent=None,
                name="",
                is_root=True,
                created_by=user,
            )
            return space
    except IntegrityError:
        return DocumentSpace.objects.get(workspace=workspace, kind=DocumentSpace.Kind.SHARED)


def _ensure_personal(workspace, user) -> DocumentSpace:
    existing = DocumentSpace.objects.filter(
        workspace=workspace,
        kind=DocumentSpace.Kind.PERSONAL,
        owner=user,
    ).first()
    if existing is not None:
        _ensure_root(existing, user)
        return existing
    try:
        with transaction.atomic():
            space = DocumentSpace.objects.create(
                workspace=workspace,
                kind=DocumentSpace.Kind.PERSONAL,
                owner=user,
            )
            DocumentFolder.objects.create(
                space=space,
                parent=None,
                name="",
                is_root=True,
                created_by=user,
            )
            return space
    except IntegrityError:
        return DocumentSpace.objects.get(
            workspace=workspace,
            kind=DocumentSpace.Kind.PERSONAL,
            owner=user,
        )


def _ensure_root(space: DocumentSpace, user) -> None:
    if DocumentFolder.objects.filter(space=space, is_root=True).exists():
        return
    DocumentFolder.objects.create(
        space=space,
        parent=None,
        name="",
        is_root=True,
        created_by=user,
    )


def _is_descendant(folder: DocumentFolder, candidate_parent: DocumentFolder) -> bool:
    current = candidate_parent
    seen: set[int] = set()
    while current is not None and current.id not in seen:
        if current.id == folder.id:
            return True
        seen.add(current.id)
        current = current.parent
    return False


def _file_name_taken(folder: DocumentFolder, filename: str, exclude_id: int | None = None) -> bool:
    query = DocumentFile.objects.filter(folder=folder, original_filename=filename)
    if exclude_id is not None:
        query = query.exclude(id=exclude_id)
    return query.exists()


def _require_base_hash(file: DocumentFile, base_hash: str) -> None:
    if clean_content_hash(base_hash) != (file.content_hash or ""):
        raise HttpError(409, "문서가 다른 곳에서 바뀌었습니다.")


def _reset_index(file: DocumentFile) -> None:
    index = _index_of(file)
    if index is None:
        index = DocumentIndex.objects.create(
            file=file,
            filename=file.original_filename,
            index_status=DocumentIndex.Status.PENDING,
        )
    else:
        index.filename = file.original_filename
        index.index_status = DocumentIndex.Status.PENDING
        index.error = ""
        index.extracted_text = ""
        index.description_ko = ""
        index.tags_ko = ""
        index.save(
            update_fields=[
                "filename",
                "index_status",
                "error",
                "extracted_text",
                "description_ko",
                "tags_ko",
                "updated_at",
            ]
        )
    schedule_index(file.id)
    file.index = index


def _record_folder(folder: DocumentFolder, op: str) -> None:
    DocumentChange.objects.create(
        space_id=folder.space_id,
        entity=DocumentChange.Entity.FOLDER,
        entity_id=folder.id,
        op=op,
        payload={
            "name": folder.name,
            "parent_id": folder.parent_id,
            "is_root": folder.is_root,
            "path": folder_path(folder),
        },
    )


def _record_file(file: DocumentFile, op: str) -> None:
    DocumentChange.objects.create(
        space_id=file.folder.space_id,
        entity=DocumentChange.Entity.FILE,
        entity_id=file.id,
        op=op,
        payload={
            "folder_id": file.folder_id,
            "original_filename": file.original_filename,
            "content_type": file.content_type,
            "size": file.size,
            "content_hash": file.content_hash,
            "path": _file_path(file.folder, file.original_filename),
        },
    )


def _serialize_change(change: DocumentChange) -> dict:
    return {
        "id": change.id,
        "space_id": change.space_id,
        "entity": change.entity,
        "entity_id": change.entity_id,
        "op": change.op,
        "payload": change.payload or {},
        "created_at": change.created_at,
    }


def _index_of(file: DocumentFile) -> DocumentIndex | None:
    try:
        return file.index
    except DocumentIndex.DoesNotExist:
        return None
