from typing import Any

from asgiref.sync import sync_to_async
from ninja import Router

from api.security import jwt_auth
from workspace.inbound import (
    BlockCreateSchema,
    BlockUpdateSchema,
    CommentCreateSchema,
    DatabaseCreateSchema,
    DatabaseUpdateSchema,
    PropertyCreateSchema,
    PropertyUpdateSchema,
    RecordCreateSchema,
    RecordQuerySchema,
    RecordUpdateSchema,
    TemplateUpdateSchema,
    TemplateWriteSchema,
    ViewUpdateSchema,
    ViewWriteSchema,
    WorkspaceCreateSchema,
    WorkspaceUpdateSchema,
)
from workspace.outbound import (
    ActivityResponseSchema,
    BlockResponseSchema,
    CommentResponseSchema,
    DatabaseDetailResponseSchema,
    DatabaseResponseSchema,
    PropertyResponseSchema,
    RecordDetailResponseSchema,
    RecordQueryResponseSchema,
    TemplateResponseSchema,
    TrashRecordResponseSchema,
    ViewResponseSchema,
    WorkspaceMemberResponseSchema,
    WorkspaceResponseSchema,
)
from workspace.utils import (
    activity_source,
    create_block,
    create_comment,
    create_database,
    create_property,
    create_record,
    create_template,
    create_view,
    create_workspace,
    delete_block,
    delete_comment,
    delete_database,
    delete_property,
    delete_record,
    delete_template,
    delete_view,
    delete_workspace,
    get_database,
    get_record,
    list_activities,
    list_comments,
    list_templates,
    list_trash,
    list_workspaces,
    query_records,
    serialize_block,
    serialize_database,
    serialize_property,
    serialize_record,
    serialize_view,
    serialize_workspace,
    list_members,
    restore_record,
    update_block,
    update_database,
    update_property,
    update_record,
    update_template,
    update_view,
    update_workspace,
    accessible_databases,
    get_membership,
)

router = Router(tags=["Workspace"])


def _dump(payload: Any, *, exclude_unset: bool = False) -> dict:
    return payload.model_dump(exclude_unset=exclude_unset)


@router.get(
    "",
    summary="[C] 워크스페이스 조회",
    description="호출자가 속한 워크스페이스 목록을 조회합니다.",
    response=list[WorkspaceResponseSchema],
    auth=jwt_auth,
)
async def list_workspace_api(request):
    return await sync_to_async(list_workspaces)(request.auth)


@router.post(
    "",
    summary="[C] 워크스페이스 생성",
    description="워크스페이스를 만들고 호출자를 소유자로 넣습니다.",
    response={201: WorkspaceResponseSchema},
    auth=jwt_auth,
)
async def create_workspace_api(request, payload: WorkspaceCreateSchema):
    data = _dump(payload)
    workspace = await sync_to_async(create_workspace)(request.auth, data["name"], data["slug"])
    return 201, workspace


@router.get(
    "/database",
    summary="[C] 데이터베이스 목록 조회",
    description=(
        "호출자가 속한 데이터베이스를 position, id 오름차순으로 돌려줍니다. "
        "section은 페이지 이름이고 section_slug는 페이지 키입니다. "
        "같은 section_slug를 한 사이드바 그룹으로 그립니다. "
        "묶음이 없으면 둘 다 빈 문자열입니다."
    ),
    response=list[DatabaseResponseSchema],
    auth=jwt_auth,
)
async def list_database_api(request):
    @sync_to_async
    def _list():
        return [
            serialize_database(database)
            for database in accessible_databases(request.auth).order_by("position", "id")
        ]

    return await _list()


@router.post(
    "/database",
    summary="[C] 데이터베이스 생성",
    description=(
        "데이터베이스를 만들고 제목 속성을 함께 만듭니다. "
        "section은 페이지 이름, section_slug는 페이지 키입니다. "
        "section_slug는 비우거나 영문 소문자로 시작하는 슬러그입니다."
    ),
    response={201: DatabaseDetailResponseSchema},
    auth=jwt_auth,
)
async def create_database_api(request, payload: DatabaseCreateSchema):
    database = await sync_to_async(create_database)(request.auth, _dump(payload))
    return 201, database


@router.get(
    "/database/{database_id}",
    summary="[C] 데이터베이스 스키마 조회",
    description=(
        "데이터베이스의 속성과 보기를 조회합니다. "
        "properties가 표 머리이고, 선택 목록은 config.options입니다. "
        "relation의 config.database_id가 연결 대상입니다."
    ),
    response=DatabaseDetailResponseSchema,
    auth=jwt_auth,
)
async def get_database_api(request, database_id: int):
    @sync_to_async
    def _get():
        return serialize_database(get_database(request.auth, database_id), detail=True)

    return await _get()


@router.patch(
    "/database/{database_id}",
    summary="[C] 데이터베이스 수정",
    description=(
        "보낸 키만 바꿉니다. section은 페이지 이름, section_slug는 페이지 키입니다. "
        "section_slug에 빈 문자열을 보내면 페이지 묶음을 해제합니다."
    ),
    response=DatabaseDetailResponseSchema,
    auth=jwt_auth,
)
async def update_database_api(request, database_id: int, payload: DatabaseUpdateSchema):
    database = await sync_to_async(update_database)(
        request.auth, database_id, _dump(payload, exclude_unset=True)
    )
    return database


@router.delete(
    "/database/{database_id}",
    summary="[C] 데이터베이스 삭제",
    description="데이터베이스와 속한 레코드를 소프트 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_database_api(request, database_id: int):
    await sync_to_async(delete_database)(request.auth, database_id)
    return 204, None


@router.get(
    "/database/{database_id}/property",
    summary="[C] 속성 목록 조회",
    description="데이터베이스 속성 목록을 조회합니다.",
    response=list[PropertyResponseSchema],
    auth=jwt_auth,
)
async def list_property_api(request, database_id: int):
    @sync_to_async
    def _list():
        database = get_database(request.auth, database_id)
        return [
            serialize_property(prop)
            for prop in database.properties.order_by("position", "id")
        ]

    return await _list()


@router.post(
    "/database/{database_id}/property",
    summary="[C] 속성 생성",
    description="데이터베이스에 속성을 추가합니다.",
    response={201: PropertyResponseSchema},
    auth=jwt_auth,
)
async def create_property_api(request, database_id: int, payload: PropertyCreateSchema):
    prop = await sync_to_async(create_property)(
        request.auth, database_id, _dump(payload)
    )
    return 201, prop


@router.patch(
    "/property/{property_id}",
    summary="[C] 속성 수정",
    description="속성 이름, 슬러그, 옵션을 수정합니다.",
    response=PropertyResponseSchema,
    auth=jwt_auth,
)
async def update_property_api(request, property_id: int, payload: PropertyUpdateSchema):
    prop = await sync_to_async(update_property)(
        request.auth, property_id, _dump(payload, exclude_unset=True)
    )
    return prop


@router.delete(
    "/property/{property_id}",
    summary="[C] 속성 삭제",
    description="속성을 소프트 삭제합니다. 제목 속성은 지울 수 없습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_property_api(request, property_id: int):
    await sync_to_async(delete_property)(request.auth, property_id)
    return 204, None


@router.get(
    "/database/{database_id}/view",
    summary="[C] 보기 목록 조회",
    description="데이터베이스 보기 목록을 조회합니다.",
    response=list[ViewResponseSchema],
    auth=jwt_auth,
)
async def list_view_api(request, database_id: int):
    @sync_to_async
    def _list():
        database = get_database(request.auth, database_id)
        return [serialize_view(view) for view in database.views.order_by("position", "id")]

    return await _list()


@router.post(
    "/database/{database_id}/view",
    summary="[C] 보기 생성",
    description="데이터베이스 보기를 추가합니다.",
    response={201: ViewResponseSchema},
    auth=jwt_auth,
)
async def create_view_api(request, database_id: int, payload: ViewWriteSchema):
    view = await sync_to_async(create_view)(request.auth, database_id, _dump(payload))
    return 201, view


@router.patch(
    "/view/{view_id}",
    summary="[C] 보기 수정",
    description="보기 이름, 필터, 정렬을 수정합니다.",
    response=ViewResponseSchema,
    auth=jwt_auth,
)
async def update_view_api(request, view_id: int, payload: ViewUpdateSchema):
    view = await sync_to_async(update_view)(
        request.auth, view_id, _dump(payload, exclude_unset=True)
    )
    return view


@router.delete(
    "/view/{view_id}",
    summary="[C] 보기 삭제",
    description="보기를 소프트 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_view_api(request, view_id: int):
    await sync_to_async(delete_view)(request.auth, view_id)
    return 204, None


@router.post(
    "/query",
    summary="[C] 레코드 조회",
    description=(
        "필터와 정렬로 레코드를 조회합니다. "
        "database_slug, database_id, view_id를 모두 비우면 통합관리대장이고, "
        "각 행의 database_slug와 database_name으로 데이터베이스를 구분합니다. "
        "view_id가 있으면 그 보기 필터를 요청 필터보다 먼저 적용합니다. "
        "q는 제목만 찾습니다."
    ),
    response=RecordQueryResponseSchema,
    auth=jwt_auth,
)
async def query_record_api(request, payload: RecordQuerySchema):
    result = await sync_to_async(query_records)(request.auth, _dump(payload))
    return result


@router.post(
    "/database/{database_id}/record",
    summary="[C] 레코드 생성",
    description="데이터베이스에 레코드를 작성합니다. values의 키는 속성 slug입니다. template_id가 있으면 그 값과 블록을 먼저 복사합니다.",
    response={201: RecordDetailResponseSchema},
    auth=jwt_auth,
)
async def create_record_api(request, database_id: int, payload: RecordCreateSchema):
    record = await sync_to_async(create_record)(
        request.auth,
        database_id,
        _dump(payload, exclude_unset=True),
        activity_source(request),
    )
    return 201, record


@router.get(
    "/record/{record_id}",
    summary="[C] 레코드 상세 조회",
    description="레코드 속성 값과 블록을 조회합니다.",
    response=RecordDetailResponseSchema,
    auth=jwt_auth,
)
async def get_record_api(request, record_id: int):
    @sync_to_async
    def _get():
        return serialize_record(get_record(request.auth, record_id), include_blocks=True)

    return await _get()


@router.patch(
    "/record/{record_id}",
    summary="[C] 레코드 수정",
    description="레코드 제목, 속성 값, 블록을 수정합니다. 보내지 않은 값은 유지합니다.",
    response=RecordDetailResponseSchema,
    auth=jwt_auth,
)
async def update_record_api(request, record_id: int, payload: RecordUpdateSchema):
    record = await sync_to_async(update_record)(
        request.auth,
        record_id,
        _dump(payload, exclude_unset=True),
        activity_source(request),
    )
    return record


@router.delete(
    "/record/{record_id}",
    summary="[C] 레코드 삭제",
    description="레코드를 휴지통으로 옮깁니다. 값과 블록은 남겨 두며 복원할 수 있습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_record_api(request, record_id: int):
    await sync_to_async(delete_record)(request.auth, record_id)
    return 204, None


@router.get(
    "/record/{record_id}/block",
    summary="[C] 블록 목록 조회",
    description="레코드 본문 블록을 조회합니다.",
    response=list[BlockResponseSchema],
    auth=jwt_auth,
)
async def list_block_api(request, record_id: int):
    @sync_to_async
    def _list():
        record = get_record(request.auth, record_id)
        return [serialize_block(block) for block in record.blocks.order_by("position", "id")]

    return await _list()


@router.post(
    "/record/{record_id}/block",
    summary="[C] 블록 생성",
    description="레코드에 블록을 추가합니다.",
    response={201: BlockResponseSchema},
    auth=jwt_auth,
)
async def create_block_api(request, record_id: int, payload: BlockCreateSchema):
    block = await sync_to_async(create_block)(
        request.auth,
        record_id,
        _dump(payload),
        activity_source(request),
    )
    return 201, block


@router.patch(
    "/block/{block_id}",
    summary="[C] 블록 수정",
    description="블록 내용과 위치를 수정합니다.",
    response=BlockResponseSchema,
    auth=jwt_auth,
)
async def update_block_api(request, block_id: int, payload: BlockUpdateSchema):
    block = await sync_to_async(update_block)(
        request.auth,
        block_id,
        _dump(payload, exclude_unset=True),
        activity_source(request),
    )
    return block


@router.delete(
    "/block/{block_id}",
    summary="[C] 블록 삭제",
    description="블록과 하위 블록을 소프트 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_block_api(request, block_id: int):
    await sync_to_async(delete_block)(request.auth, block_id, activity_source(request))
    return 204, None


@router.get(
    "/database/{database_id}/template",
    summary="[C] 템플릿 목록 조회",
    description="데이터베이스 템플릿 목록을 조회합니다.",
    response=list[TemplateResponseSchema],
    auth=jwt_auth,
)
async def list_template_api(request, database_id: int):
    return await sync_to_async(list_templates)(request.auth, database_id)


@router.post(
    "/database/{database_id}/template",
    summary="[C] 템플릿 생성",
    description="새 레코드에 복사할 제목, 값, 블록을 저장합니다.",
    response={201: TemplateResponseSchema},
    auth=jwt_auth,
)
async def create_template_api(request, database_id: int, payload: TemplateWriteSchema):
    template = await sync_to_async(create_template)(
        request.auth, database_id, _dump(payload)
    )
    return 201, template


@router.patch(
    "/template/{template_id}",
    summary="[C] 템플릿 수정",
    description="템플릿 이름, 값, 블록을 수정합니다.",
    response=TemplateResponseSchema,
    auth=jwt_auth,
)
async def update_template_api(request, template_id: int, payload: TemplateUpdateSchema):
    template = await sync_to_async(update_template)(
        request.auth, template_id, _dump(payload, exclude_unset=True)
    )
    return template


@router.delete(
    "/template/{template_id}",
    summary="[C] 템플릿 삭제",
    description="템플릿을 소프트 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_template_api(request, template_id: int):
    await sync_to_async(delete_template)(request.auth, template_id)
    return 204, None


@router.get(
    "/record/{record_id}/activity",
    summary="[C] 활동 이력 조회",
    description="레코드 생성·수정 스냅샷을 최근 50건 조회합니다.",
    response=list[ActivityResponseSchema],
    auth=jwt_auth,
)
async def list_activity_api(request, record_id: int):
    return await sync_to_async(list_activities)(request.auth, record_id)


@router.get(
    "/record/{record_id}/comment",
    summary="[C] 댓글 목록 조회",
    description="레코드 댓글을 오래된 순으로 조회합니다.",
    response=list[CommentResponseSchema],
    auth=jwt_auth,
)
async def list_comment_api(request, record_id: int):
    return await sync_to_async(list_comments)(request.auth, record_id)


@router.post(
    "/record/{record_id}/comment",
    summary="[C] 댓글 작성",
    description="레코드에 댓글 또는 한 단계 답글을 작성합니다.",
    response={201: CommentResponseSchema},
    auth=jwt_auth,
)
async def create_comment_api(request, record_id: int, payload: CommentCreateSchema):
    comment = await sync_to_async(create_comment)(
        request.auth, record_id, _dump(payload, exclude_unset=True)
    )
    return 201, comment


@router.delete(
    "/comment/{comment_id}",
    summary="[C] 댓글 삭제",
    description="댓글을 소프트 삭제합니다. 작성자, 소유자, 관리자만 삭제할 수 있습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_comment_api(request, comment_id: int):
    await sync_to_async(delete_comment)(request.auth, comment_id)
    return 204, None


@router.post(
    "/record/{record_id}/restore",
    summary="[C] 레코드 복원",
    description="휴지통의 레코드를 복원합니다. 값과 블록은 삭제 전에 남겨 둔 것을 그대로 되돌립니다.",
    response=RecordDetailResponseSchema,
    auth=jwt_auth,
)
async def restore_record_api(request, record_id: int):
    return await sync_to_async(restore_record)(request.auth, record_id)


@router.get(
    "/{workspace_id}/trash",
    summary="[C] 휴지통 조회",
    description="워크스페이스에서 지운 레코드 최근 100건을 조회합니다.",
    response=list[TrashRecordResponseSchema],
    auth=jwt_auth,
)
async def list_trash_api(request, workspace_id: int):
    return await sync_to_async(list_trash)(request.auth, workspace_id)


@router.get(
    "/{workspace_id}/member",
    summary="[C] 워크스페이스 멤버 조회",
    description="워크스페이스 멤버의 사용자 id, 이름, 역할을 조회합니다.",
    response=list[WorkspaceMemberResponseSchema],
    auth=jwt_auth,
)
async def list_member_api(request, workspace_id: int):
    return await sync_to_async(list_members)(request.auth, workspace_id)


@router.get(
    "/{workspace_id}",
    summary="[C] 워크스페이스 상세 조회",
    description="워크스페이스 하나를 조회합니다.",
    response=WorkspaceResponseSchema,
    auth=jwt_auth,
)
async def get_workspace_api(request, workspace_id: int):
    @sync_to_async
    def _get():
        membership = get_membership(request.auth, workspace_id)
        return serialize_workspace(membership.workspace, membership.role)

    return await _get()


@router.patch(
    "/{workspace_id}",
    summary="[C] 워크스페이스 수정",
    description="워크스페이스 이름과 슬러그를 수정합니다.",
    response=WorkspaceResponseSchema,
    auth=jwt_auth,
)
async def update_workspace_api(request, workspace_id: int, payload: WorkspaceUpdateSchema):
    workspace = await sync_to_async(update_workspace)(
        request.auth, workspace_id, _dump(payload, exclude_unset=True)
    )
    return workspace


@router.delete(
    "/{workspace_id}",
    summary="[C] 워크스페이스 삭제",
    description="워크스페이스를 소프트 삭제합니다. 소유자만 삭제할 수 있습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_workspace_api(request, workspace_id: int):
    await sync_to_async(delete_workspace)(request.auth, workspace_id)
    return 204, None
