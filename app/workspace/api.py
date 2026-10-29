from typing import Any

from asgiref.sync import sync_to_async
from ninja import Router

from api.security import jwt_auth
from workspace.inbound import (
    BlockCreateSchema,
    BlockUpdateSchema,
    DatabaseCreateSchema,
    DatabaseUpdateSchema,
    PropertyCreateSchema,
    PropertyUpdateSchema,
    RecordCreateSchema,
    RecordQuerySchema,
    RecordUpdateSchema,
    ViewUpdateSchema,
    ViewWriteSchema,
    WorkspaceCreateSchema,
    WorkspaceUpdateSchema,
)
from workspace.outbound import (
    BlockResponseSchema,
    DatabaseDetailResponseSchema,
    DatabaseResponseSchema,
    PropertyResponseSchema,
    RecordDetailResponseSchema,
    RecordQueryResponseSchema,
    ViewResponseSchema,
    WorkspaceMemberResponseSchema,
    WorkspaceResponseSchema,
)
from workspace.utils import (
    activity_source,
    create_block,
    create_database,
    create_property,
    create_record,
    create_view,
    create_workspace,
    delete_block,
    delete_database,
    delete_property,
    delete_record,
    delete_view,
    delete_workspace,
    get_database,
    get_record,
    list_workspaces,
    query_records,
    serialize_block,
    serialize_database,
    serialize_property,
    serialize_record,
    serialize_view,
    serialize_workspace,
    list_members,
    update_block,
    update_database,
    update_property,
    update_record,
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
    description="호출자가 속한 워크스페이스의 데이터베이스 목록을 조회합니다.",
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
    description="데이터베이스를 만들고 제목 속성을 함께 만듭니다.",
    response={201: DatabaseDetailResponseSchema},
    auth=jwt_auth,
)
async def create_database_api(request, payload: DatabaseCreateSchema):
    database = await sync_to_async(create_database)(request.auth, _dump(payload))
    return 201, database


@router.get(
    "/database/{database_id}",
    summary="[C] 데이터베이스 스키마 조회",
    description="데이터베이스의 속성과 보기를 조회합니다.",
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
    description="데이터베이스 이름, 슬러그, 설명을 수정합니다.",
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
    description="워크스페이스 레코드를 필터와 정렬로 조회합니다. 데이터베이스를 비우면 통합대장처럼 전체를 봅니다.",
    response=RecordQueryResponseSchema,
    auth=jwt_auth,
)
async def query_record_api(request, payload: RecordQuerySchema):
    result = await sync_to_async(query_records)(request.auth, _dump(payload))
    return result


@router.post(
    "/database/{database_id}/record",
    summary="[C] 레코드 생성",
    description="데이터베이스에 레코드를 작성합니다. values의 키는 속성 slug입니다.",
    response={201: RecordDetailResponseSchema},
    auth=jwt_auth,
)
async def create_record_api(request, database_id: int, payload: RecordCreateSchema):
    record = await sync_to_async(create_record)(
        request.auth,
        database_id,
        _dump(payload),
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
    description="레코드를 소프트 삭제합니다.",
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
