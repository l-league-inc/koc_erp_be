from asgiref.sync import sync_to_async
from ninja import Router
from ninja.errors import HttpError

from api.security import jwt_auth
from document.inbound import (
    FileCreateSchema,
    FileReplaceSchema,
    FileReplaceUploadSchema,
    FileUpdateSchema,
    FolderCreateSchema,
    FolderUpdateSchema,
    UploadRequestSchema,
)
from document.outbound import (
    ChangeListResponseSchema,
    DownloadResponseSchema,
    FileDetailResponseSchema,
    FileResponseSchema,
    FolderResponseSchema,
    MailLogResponseSchema,
    SearchHitSchema,
    SpaceResponseSchema,
    SyncCursorResponseSchema,
    UploadResponseSchema,
)
from document.utils import (
    client_source,
    create_download,
    create_file,
    create_folder,
    create_replace_upload,
    create_sync_url,
    create_upload,
    delete_file,
    delete_folder,
    ensure_spaces,
    get_file_detail,
    list_changes,
    list_files,
    list_folders,
    list_mail_logs,
    reindex_file,
    replace_file_content,
    search_files,
    sync_cursor,
    update_file,
    update_folder,
)

router = Router(tags=["Document"])


def _dump(payload, *, exclude_unset: bool = False) -> dict:
    return payload.model_dump(exclude_unset=exclude_unset)


@router.get(
    "/{workspace_id}/space",
    summary="[C] 문서함 조회",
    description="공유 문서함과 내 개인 문서함을 조회합니다. 없으면 만듭니다. 다른 멤버의 개인 문서함은 포함하지 않습니다.",
    response=list[SpaceResponseSchema],
    auth=jwt_auth,
)
async def list_space_api(request, workspace_id: int):
    return await sync_to_async(ensure_spaces)(request.auth, workspace_id)


@router.get(
    "/{workspace_id}/sync-cursor",
    summary="[C] 문서 동기화 커서",
    description="문서함의 현재 변경 커서를 조회합니다. 최초 동기화는 이 값을 받은 뒤 폴더와 파일 목록으로 트리를 만듭니다.",
    response=SyncCursorResponseSchema,
    auth=jwt_auth,
)
async def sync_cursor_api(request, workspace_id: int, space_id: int):
    return await sync_to_async(sync_cursor)(request.auth, workspace_id, space_id)


@router.get(
    "/{workspace_id}/changes",
    summary="[C] 문서 변경 목록",
    description="커서 이후에 생긴 폴더·파일 변경을 최대 200건 반환합니다. 더 있으면 next_cursor로 이어서 조회합니다.",
    response=ChangeListResponseSchema,
    auth=jwt_auth,
)
async def list_changes_api(request, workspace_id: int, space_id: int, cursor: int = 0):
    return await sync_to_async(list_changes)(request.auth, workspace_id, space_id, cursor)


@router.get(
    "/{workspace_id}/folder",
    summary="[C] 문서 폴더 조회",
    description="문서함의 하위 폴더를 조회합니다. parent_id가 없으면 루트의 자식을 반환합니다.",
    response=list[FolderResponseSchema],
    auth=jwt_auth,
)
async def list_folder_api(
    request,
    workspace_id: int,
    space_id: int,
    parent_id: int | None = None,
):
    return await sync_to_async(list_folders)(request.auth, workspace_id, space_id, parent_id)


@router.post(
    "/{workspace_id}/folder",
    summary="[C] 문서 폴더 생성",
    description="상위 폴더 아래에 폴더를 만듭니다.",
    response={201: FolderResponseSchema},
    auth=jwt_auth,
)
async def create_folder_api(request, workspace_id: int, payload: FolderCreateSchema):
    data = _dump(payload)
    folder = await sync_to_async(create_folder)(
        request.auth,
        workspace_id,
        data["parent_id"],
        data["name"],
    )
    return 201, folder


@router.patch(
    "/{workspace_id}/folder/{folder_id}",
    summary="[C] 문서 폴더 수정",
    description="폴더 이름을 바꾸거나 같은 문서함 안에서 옮깁니다.",
    response=FolderResponseSchema,
    auth=jwt_auth,
)
async def update_folder_api(
    request,
    workspace_id: int,
    folder_id: int,
    payload: FolderUpdateSchema,
):
    data = _dump(payload, exclude_unset=True)
    if not data:
        raise HttpError(400, "바꿀 값이 필요합니다.")
    return await sync_to_async(update_folder)(request.auth, workspace_id, folder_id, data)


@router.delete(
    "/{workspace_id}/folder/{folder_id}",
    summary="[C] 문서 폴더 삭제",
    description="비어 있는 폴더를 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_folder_api(request, workspace_id: int, folder_id: int):
    await sync_to_async(delete_folder)(request.auth, workspace_id, folder_id)
    return 204, None


@router.post(
    "/{workspace_id}/upload",
    summary="[C] 문서 업로드 URL 생성",
    description="비공개 S3에 문서를 올리기 위한 URL을 만듭니다. 최대 50MB이며 만료는 300초입니다.",
    response=UploadResponseSchema,
    auth=jwt_auth,
)
async def create_upload_api(request, workspace_id: int, payload: UploadRequestSchema):
    data = _dump(payload)
    return await sync_to_async(create_upload)(
        request.auth,
        workspace_id,
        data["folder_id"],
        data["file_name"],
        data["content_type"],
        data["size"],
    )


@router.get(
    "/{workspace_id}/file/search",
    summary="[C] 문서 검색",
    description=(
        "공유 문서와 내 개인 문서만 검색합니다. "
        "결과는 파일 id, 이름, 폴더 경로, 요약, 점수입니다. "
        "본문은 문서 상세 조회로 읽습니다."
    ),
    response=list[SearchHitSchema],
    auth=jwt_auth,
)
async def search_file_api(request, workspace_id: int, q: str):
    return await sync_to_async(search_files)(request.auth, workspace_id, q)


@router.get(
    "/{workspace_id}/file/{file_id}/mail",
    summary="[C] 메일 발송 이력 조회",
    description="문서의 메일 발송 이력을 조회합니다. 발송 기능은 아직 없어 목록이 비어 있을 수 있습니다.",
    response=list[MailLogResponseSchema],
    auth=jwt_auth,
)
async def list_mail_api(request, workspace_id: int, file_id: int):
    return await sync_to_async(list_mail_logs)(request.auth, workspace_id, file_id)


@router.post(
    "/{workspace_id}/file/{file_id}/download",
    summary="[C] 다운로드 URL 생성",
    description="문서 다운로드 URL을 만들고 다운로드 이력을 남깁니다. URL은 300초 뒤 만료됩니다.",
    response=DownloadResponseSchema,
    auth=jwt_auth,
)
async def create_download_api(request, workspace_id: int, file_id: int):
    source = client_source(request)
    return await sync_to_async(create_download)(request.auth, workspace_id, file_id, source)


@router.post(
    "/{workspace_id}/file/{file_id}/sync-url",
    summary="[C] 동기화 다운로드 URL",
    description="동기화 클라이언트가 파일 내용을 받기 위한 URL을 만듭니다. 다운로드 이력은 남기지 않습니다.",
    response=DownloadResponseSchema,
    auth=jwt_auth,
)
async def create_sync_url_api(request, workspace_id: int, file_id: int):
    return await sync_to_async(create_sync_url)(request.auth, workspace_id, file_id)


@router.post(
    "/{workspace_id}/file/{file_id}/upload",
    summary="[C] 문서 내용 교체 URL",
    description="기존 문서의 새 내용을 올리기 위한 URL을 만듭니다. base_hash가 현재 해시와 다르면 409입니다.",
    response=UploadResponseSchema,
    auth=jwt_auth,
)
async def create_replace_upload_api(
    request,
    workspace_id: int,
    file_id: int,
    payload: FileReplaceUploadSchema,
):
    data = _dump(payload)
    return await sync_to_async(create_replace_upload)(
        request.auth,
        workspace_id,
        file_id,
        data["content_type"],
        data["size"],
        data["base_hash"],
    )


@router.post(
    "/{workspace_id}/file/{file_id}/content",
    summary="[C] 문서 내용 교체 확정",
    description="업로드가 끝난 새 내용으로 문서를 바꿉니다. base_hash가 현재 해시와 다르면 409입니다.",
    response=FileDetailResponseSchema,
    auth=jwt_auth,
)
async def replace_file_content_api(
    request,
    workspace_id: int,
    file_id: int,
    payload: FileReplaceSchema,
):
    return await sync_to_async(replace_file_content)(
        request.auth,
        workspace_id,
        file_id,
        _dump(payload),
    )


@router.post(
    "/{workspace_id}/file/{file_id}/reindex",
    summary="[C] 문서 색인 다시 실행",
    description="올린 사람이 문서 색인을 다시 실행합니다.",
    response=FileDetailResponseSchema,
    auth=jwt_auth,
)
async def reindex_file_api(request, workspace_id: int, file_id: int):
    return await sync_to_async(reindex_file)(request.auth, workspace_id, file_id)


@router.get(
    "/{workspace_id}/file/{file_id}",
    summary="[C] 문서 상세 조회",
    description="문서 메타, 한국어 요약, 추출 본문을 조회합니다. 개인 문서는 소유자만 조회합니다.",
    response=FileDetailResponseSchema,
    auth=jwt_auth,
)
async def get_file_api(request, workspace_id: int, file_id: int):
    return await sync_to_async(get_file_detail)(request.auth, workspace_id, file_id)


@router.patch(
    "/{workspace_id}/file/{file_id}",
    summary="[C] 문서 수정",
    description="문서 이름을 바꾸거나 같은 문서함의 다른 폴더로 옮깁니다.",
    response=FileResponseSchema,
    auth=jwt_auth,
)
async def update_file_api(request, workspace_id: int, file_id: int, payload: FileUpdateSchema):
    data = _dump(payload, exclude_unset=True)
    if not data:
        raise HttpError(400, "바꿀 값이 필요합니다.")
    return await sync_to_async(update_file)(request.auth, workspace_id, file_id, data)


@router.delete(
    "/{workspace_id}/file/{file_id}",
    summary="[C] 문서 삭제",
    description="문서를 삭제합니다. 올린 사람 또는 워크스페이스 소유자·관리자만 지울 수 있습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_file_api(request, workspace_id: int, file_id: int):
    await sync_to_async(delete_file)(request.auth, workspace_id, file_id)
    return 204, None


@router.get(
    "/{workspace_id}/file",
    summary="[C] 문서 목록 조회",
    description="폴더 안의 문서를 조회합니다.",
    response=list[FileResponseSchema],
    auth=jwt_auth,
)
async def list_file_api(request, workspace_id: int, folder_id: int):
    return await sync_to_async(list_files)(request.auth, workspace_id, folder_id)


@router.post(
    "/{workspace_id}/file",
    summary="[C] 문서 등록",
    description="업로드가 끝난 문서를 폴더에 등록하고 색인을 예약합니다.",
    response={201: FileDetailResponseSchema},
    auth=jwt_auth,
)
async def create_file_api(request, workspace_id: int, payload: FileCreateSchema):
    created = await sync_to_async(create_file)(request.auth, workspace_id, _dump(payload))
    return 201, created
