from ninja import Router, Query
from ninja.pagination import paginate
from api.security import admin_auth
from notice.inbound import NoticeCreateSchema, NoticeUpdateSchema, NoticeFilterSchema
from notice.outbound import NoticeResponseSchema
from typing import List
from asgiref.sync import sync_to_async
from notice.models import Notice
from notice.utils import (
    get_notice_admin_by_id,
    get_notice_by_id,
    make_notitication_from_notice,
)
from django.db.models import F


router = Router(tags=["Notice"])


@router.get(
    "/admin",
    summary="[A] 관리자 공지사항 목록",
    description="공지사항 목록을 조회합니다.",
    response=List[NoticeResponseSchema],
    auth=admin_auth,
)
@paginate
async def get_admin_notices(request, filters: NoticeFilterSchema = Query(...)):
    @sync_to_async
    def get_admin_notices():
        queryset = Notice.objects.all().order_by("-created_at")
        queryset = filters.filter(queryset)
        return queryset

    notices = await get_admin_notices()

    return notices


@router.post(
    "/admin",
    summary="[A] 관리자 공지사항 생성",
    description="공지사항을 생성합니다.",
    response={201: NoticeResponseSchema},
    auth=admin_auth,
)
async def create_notice(request, payload: NoticeCreateSchema):
    notice = await Notice.objects.acreate(**payload.dict())
    if notice.hidden is False and notice.is_notification_sent is False:
        await make_notitication_from_notice(notice)
        notice.is_notification_sent = True
        await notice.asave(update_fields=["is_notification_sent"])
    return 201, notice


@router.get(
    "/admin/{notice_id}",
    summary="[A] 관리자 공지사항 상세 조회",
    description="공지사항 상세를 조회합니다.",
    response={200: NoticeResponseSchema},
    auth=admin_auth,
)
async def get_admin_notice(request, notice_id: int):
    notice = await get_notice_admin_by_id(notice_id)
    return notice


@router.patch(
    "/admin/{notice_id}",
    summary="[A] 관리자 공지사항 수정",
    description="공지사항을 수정합니다.",
    response={200: NoticeResponseSchema},
    auth=admin_auth,
)
async def update_notice(request, notice_id: int, payload: NoticeUpdateSchema):
    notice = await get_notice_admin_by_id(notice_id)
    data = payload.dict(exclude_unset=True)
    for key, value in data.items():
        setattr(notice, key, value)
    await notice.asave()
    # hidden이 True -> False로 변경되어 공개되었고, 아직 알림이 전송되지 않은 경우 알림 생성
    if notice.hidden is False and notice.is_notification_sent is False:
        await make_notitication_from_notice(notice)
        notice.is_notification_sent = True
        await notice.asave(update_fields=["is_notification_sent"])
    return notice


@router.delete(
    "/admin/{notice_id}",
    summary="[A] 관리자 공지사항 삭제",
    description="공지사항을 삭제합니다.",
    response={204: None},
    auth=admin_auth,
)
async def delete_notice(request, notice_id: int):
    notice = await get_notice_admin_by_id(notice_id)
    await notice.adelete()
    return 204, None


@router.get(
    "",
    summary="[C] 공지사항 목록",
    description="공지사항 목록을 조회합니다.",
    response=List[NoticeResponseSchema],
)
@paginate
async def get_notices(request, filters: NoticeFilterSchema = Query(...)):
    @sync_to_async
    def get_notices():
        queryset = Notice.objects.filter(hidden=False).order_by("-created_at")
        queryset = filters.filter(queryset)
        return queryset

    notices = await get_notices()

    return notices


@router.get(
    "/{notice_id}",
    summary="[C] 공지사항 상세 조회",
    description="공지사항 상세를 조회합니다.",
    response={200: NoticeResponseSchema},
)
async def get_notice(request, notice_id: int):

    notice = await get_notice_by_id(notice_id)

    @sync_to_async
    def increase_view_count():
        Notice.objects.filter(id=notice_id).update(view_count=F("view_count") + 1)

    await increase_view_count()

    return notice
