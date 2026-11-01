from asgiref.sync import sync_to_async
from ninja import Query, Router

from api.security import jwt_auth
from assistant.agent import (
    confirm_actions,
    create_session,
    get_session_detail,
    list_sessions,
    send_message,
)
from assistant.schemas import (
    ConfirmResultSchema,
    ConfirmSchema,
    MessageCreateSchema,
    MessageResultSchema,
    SessionCreateSchema,
    SessionDetailSchema,
    SessionListItemSchema,
    SessionResponseSchema,
    SkillCreateSchema,
    SkillResponseSchema,
    SkillUpdateSchema,
    WorkbotDraftResponseSchema,
    WorkbotDraftSchema,
    WorkbotResponseSchema,
    WorkbotRunResponseSchema,
    WorkbotStatsResponseSchema,
    WorkbotUpdateSchema,
    WorkbotWriteSchema,
)
from assistant.skillbook import create_skill, delete_skill, list_skills, update_skill
from assistant.workbot import (
    confirm_run,
    create_workbot,
    delete_workbot,
    draft_workbot,
    list_runs,
    list_workbots,
    run_workbot_by_id,
    update_workbot,
    workbot_stats,
)

agent_router = Router(tags=["Agent"])
workbot_router = Router(tags=["Workbot"])


def _dump(payload, *, exclude_unset: bool = False) -> dict:
    return payload.model_dump(exclude_unset=exclude_unset)


@agent_router.post(
    "/session",
    summary="[C] 업무 대화 시작",
    description="워크스페이스 업무 대화를 시작합니다. database_slug가 없으면 전체 영역입니다.",
    response={201: SessionResponseSchema},
    auth=jwt_auth,
)
async def create_session_api(request, payload: SessionCreateSchema):
    session = await sync_to_async(create_session)(
        request.auth,
        payload.workspace_id,
        payload.database_slug,
    )
    return 201, session


@agent_router.get(
    "/session",
    summary="[C] 업무 대화 목록 조회",
    description="호출자의 최근 대화 50개를 조회합니다. workspace_id가 있으면 그 공간만 돌려줍니다.",
    response=list[SessionListItemSchema],
    auth=jwt_auth,
)
async def list_session_api(request, workspace_id: int | None = Query(None)):
    return await sync_to_async(list_sessions)(request.auth, workspace_id)


@agent_router.get(
    "/session/{session_id}",
    summary="[C] 업무 대화 조회",
    description="대화의 메시지와 초안을 시간순으로 조회합니다.",
    response=SessionDetailSchema,
    auth=jwt_auth,
)
async def get_session_api(request, session_id: int):
    return await sync_to_async(get_session_detail)(request.auth, session_id)


@agent_router.post(
    "/session/{session_id}/message",
    summary="[C] 업무 대화 메시지",
    description="문장을 해석해 조회하고, 레코드 생성·수정은 초안으로 돌려줍니다.",
    response=MessageResultSchema,
    auth=jwt_auth,
)
async def send_message_api(request, session_id: int, payload: MessageCreateSchema):
    return await sync_to_async(send_message)(request.auth, session_id, payload.content)


@agent_router.post(
    "/session/{session_id}/confirm",
    summary="[C] 업무 초안 확정",
    description="대기 중인 초안만 워크스페이스에 저장합니다.",
    response=ConfirmResultSchema,
    auth=jwt_auth,
)
async def confirm_session_api(request, session_id: int, payload: ConfirmSchema):
    return await sync_to_async(confirm_actions)(request.auth, session_id, payload.action_ids)


@agent_router.get(
    "/skill",
    summary="[C] 업무 스킬 목록 조회",
    description="고정 스킬과 워크스페이스 스킬을 조회합니다. 고정 스킬은 id가 없습니다.",
    response=list[SkillResponseSchema],
    auth=jwt_auth,
)
async def list_skill_api(request, workspace_id: int = Query(...)):
    return await sync_to_async(list_skills)(request.auth, workspace_id)


@agent_router.post(
    "/skill",
    summary="[C] 업무 스킬 생성",
    description="워크스페이스 스킬을 만듭니다. 고정 스킬 이름은 쓸 수 없습니다.",
    response={201: SkillResponseSchema},
    auth=jwt_auth,
)
async def create_skill_api(request, payload: SkillCreateSchema):
    skill = await sync_to_async(create_skill)(request.auth, _dump(payload))
    return 201, skill


@agent_router.patch(
    "/skill/{skill_id}",
    summary="[C] 업무 스킬 수정",
    description="설명, 본문, 활성 상태를 수정합니다. 고정 스킬은 수정할 수 없습니다.",
    response=SkillResponseSchema,
    auth=jwt_auth,
)
async def update_skill_api(request, skill_id: int, payload: SkillUpdateSchema):
    return await sync_to_async(update_skill)(
        request.auth,
        skill_id,
        _dump(payload, exclude_unset=True),
    )


@agent_router.delete(
    "/skill/{skill_id}",
    summary="[C] 업무 스킬 삭제",
    description="워크스페이스 스킬을 소프트 삭제합니다. 고정 스킬은 삭제할 수 없습니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_skill_api(request, skill_id: int):
    await sync_to_async(delete_skill)(request.auth, skill_id)
    return 204, None


@workbot_router.get(
    "",
    summary="[C] 워크봇 목록 조회",
    description="속한 워크스페이스의 워크봇을 조회합니다.",
    response=list[WorkbotResponseSchema],
    auth=jwt_auth,
)
async def list_workbot_api(request):
    return await sync_to_async(list_workbots)(request.auth)


@workbot_router.post(
    "",
    summary="[C] 워크봇 생성",
    description="저장된 실행 명세와 일정으로 워크봇을 만듭니다.",
    response={201: WorkbotResponseSchema},
    auth=jwt_auth,
)
async def create_workbot_api(request, payload: WorkbotWriteSchema):
    bot = await sync_to_async(create_workbot)(request.auth, _dump(payload))
    return 201, bot


@workbot_router.get(
    "/stats",
    summary="[C] 워크봇 통계 조회",
    description="활성 수, 이번 달 실행 수, 성공률, 절약 시간을 조회합니다.",
    response=WorkbotStatsResponseSchema,
    auth=jwt_auth,
)
async def workbot_stats_api(request):
    return await sync_to_async(workbot_stats)(request.auth)


@workbot_router.get(
    "/run",
    summary="[C] 워크봇 실행 이력 조회",
    description="최근 실행 50건을 조회합니다.",
    response=list[WorkbotRunResponseSchema],
    auth=jwt_auth,
)
async def list_run_api(request, workbot_id: int | None = Query(None)):
    return await sync_to_async(list_runs)(request.auth, workbot_id)


@workbot_router.post(
    "/draft",
    summary="[C] 워크봇 초안 작성",
    description="자연어 지시를 워크봇 초안으로 바꿉니다. 저장하지 않습니다.",
    response=WorkbotDraftResponseSchema,
    auth=jwt_auth,
)
async def draft_workbot_api(request, payload: WorkbotDraftSchema):
    return await sync_to_async(draft_workbot)(
        request.auth,
        payload.workspace_id,
        payload.instruction,
    )


@workbot_router.post(
    "/{workbot_id}/run",
    summary="[C] 워크봇 실행",
    description="저장된 명세로 워크봇을 지금 실행합니다.",
    response=WorkbotRunResponseSchema,
    auth=jwt_auth,
)
async def run_workbot_api(request, workbot_id: int):
    return await sync_to_async(run_workbot_by_id)(request.auth, workbot_id)


@workbot_router.post(
    "/run/{run_id}/confirm",
    summary="[C] 워크봇 실행 확정",
    description="확인 대기 중인 실행을 반영합니다.",
    response=WorkbotRunResponseSchema,
    auth=jwt_auth,
)
async def confirm_run_api(request, run_id: int):
    return await sync_to_async(confirm_run)(request.auth, run_id)


@workbot_router.patch(
    "/{workbot_id}",
    summary="[C] 워크봇 수정",
    description="이름, 일정, 명세, 활성 상태를 수정합니다.",
    response=WorkbotResponseSchema,
    auth=jwt_auth,
)
async def update_workbot_api(request, workbot_id: int, payload: WorkbotUpdateSchema):
    return await sync_to_async(update_workbot)(
        request.auth,
        workbot_id,
        _dump(payload, exclude_unset=True),
    )


@workbot_router.delete(
    "/{workbot_id}",
    summary="[C] 워크봇 삭제",
    description="워크봇을 소프트 삭제합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_workbot_api(request, workbot_id: int):
    await sync_to_async(delete_workbot)(request.auth, workbot_id)
    return 204, None
