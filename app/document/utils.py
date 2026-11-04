import threading

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import IntegrityError, transaction
from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Coalesce
from ninja.errors import HttpError

from document.indexer import run_index
from document.models import (
    DocumentDownload,
    DocumentFile,
    DocumentFolder,
    DocumentIndex,
    DocumentMailLog,
    DocumentSpace,
)
from document.storage import (
    PRESIGN_EXPIRES,
    assert_object_key,
    assert_size,
    build_object_key,
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
    folders = DocumentFolder.objects.filter(parent=parent).order_by("name", "id")
    return [serialize_folder(folder) for folder in folders]


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
    return serialize_folder(folder)


def delete_folder(user, workspace_id: int, folder_id: int) -> None:
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    if folder.is_root:
        raise HttpError(400, "최상위 폴더는 지울 수 없습니다.")
    if DocumentFolder.objects.filter(parent=folder).exists():
        raise HttpError(400, "하위 폴더가 있는 폴더는 지울 수 없습니다.")
    if DocumentFile.objects.filter(folder=folder).exists():
        raise HttpError(400, "파일이 있는 폴더는 지울 수 없습니다.")
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
    try:
        file = DocumentFile.objects.create(
            folder=folder,
            original_filename=filename,
            object_key=object_key,
            content_type=content_type,
            size=int(data["size"]),
            uploaded_by=user,
        )
    except IntegrityError:
        raise HttpError(400, "이미 등록된 문서입니다.") from None
    DocumentIndex.objects.create(
        file=file,
        filename=filename,
        index_status=DocumentIndex.Status.PENDING,
        index_source=DocumentIndex.Source.LOCAL,
    )
    schedule_index(file.id)
    return serialize_file(file, detail=True)


def list_files(user, workspace_id: int, folder_id: int) -> list[dict]:
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    files = (
        DocumentFile.objects.filter(folder=folder)
        .select_related("folder__space", "index", "uploaded_by")
        .order_by("-created_at", "-id")
    )
    return [serialize_file(file, detail=False) for file in files]


def get_file_detail(user, workspace_id: int, file_id: int) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    return serialize_file(file, detail=True)


def move_file(user, workspace_id: int, file_id: int, folder_id: int) -> dict:
    _membership, file = _get_file(user, workspace_id, file_id)
    _membership, folder = _get_folder(user, workspace_id, folder_id)
    if folder.space_id != file.folder.space_id:
        raise HttpError(400, "다른 문서함으로는 옮길 수 없습니다.")
    file.folder = folder
    file.save(update_fields=["folder", "updated_at"])
    return serialize_file(file, detail=False)


def delete_file(user, workspace_id: int, file_id: int) -> None:
    membership, file = _get_file(user, workspace_id, file_id)
    if file.uploaded_by_id != user.id and membership.role not in _MANAGE_ROLES:
        raise HttpError(403, "문서를 지울 권한이 없습니다.")
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
    hits = []
    for index in rows:
        score = float(index.rank or 0)
        if score <= 0:
            score = 0.01
        hits.append(
            {
                "id": index.file_id,
                "original_filename": index.file.original_filename,
                "folder_id": index.file.folder_id,
                "folder_path": folder_path(index.file.folder),
                "description_ko": index.description_ko,
                "score": score,
            }
        )
    return hits


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


def serialize_folder(folder: DocumentFolder) -> dict:
    return {
        "id": folder.id,
        "space_id": folder.space_id,
        "parent_id": folder.parent_id,
        "name": folder.name,
        "is_root": folder.is_root,
        "path": folder_path(folder),
        "created_at": folder.created_at,
    }


def serialize_file(file: DocumentFile, *, detail: bool) -> dict:
    folder = file.folder
    space = folder.space
    index = _index_of(file)
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
        "path": _file_path(folder, file.original_filename),
        "index_status": index.index_status if index else DocumentIndex.Status.PENDING,
        "index_source": index.index_source if index else DocumentIndex.Source.LOCAL,
        "description_ko": index.description_ko if index else "",
        "tags_ko": _tags(index.tags_ko if index else ""),
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
    if not cleaned or "/" in cleaned or "\\" in cleaned:
        raise HttpError(400, "폴더 이름이 올바르지 않습니다.")
    if len(cleaned) > 255:
        raise HttpError(400, "폴더 이름은 255자를 넘길 수 없습니다.")
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


def _index_of(file: DocumentFile) -> DocumentIndex | None:
    try:
        return file.index
    except DocumentIndex.DoesNotExist:
        return None
