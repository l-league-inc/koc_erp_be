from asgiref.sync import sync_to_async
from ninja import Router

from api.security import jwt_auth
from attendance import service
from attendance.schema import AttendanceActionSchema, AttendanceStatusSchema

router = Router(tags=["Attendance"])


@router.get(
    "/today",
    summary="[C] 오늘 출퇴근 조회",
    description="로그인한 사용자의 오늘 출근·퇴근 상태입니다. 출근 전 none, 출근만 됨 in, 퇴근까지 됨 out입니다.",
    response=AttendanceStatusSchema,
    auth=jwt_auth,
)
async def today_api(request, workspace_id: int):
    return await sync_to_async(service.today_status)(request.auth, workspace_id)


@router.post(
    "/clock-in",
    summary="[C] 출근",
    description="지금 시각을 출근시각에 넣습니다. 시각은 받지 않습니다. 오늘 행이 있고 출근시각만 비어 있으면 그 칸을 채웁니다.",
    response=AttendanceStatusSchema,
    auth=jwt_auth,
)
async def clock_in_api(request, payload: AttendanceActionSchema):
    return await sync_to_async(service.clock_in)(request.auth, payload.workspace_id)


@router.post(
    "/clock-out",
    summary="[C] 퇴근",
    description="오늘 출근 행의 퇴근시각에 지금 시각을 넣습니다. 시각은 받지 않습니다.",
    response=AttendanceStatusSchema,
    auth=jwt_auth,
)
async def clock_out_api(request, payload: AttendanceActionSchema):
    return await sync_to_async(service.clock_out)(request.auth, payload.workspace_id)
