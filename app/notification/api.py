from ninja import Router, Query
from ninja.errors import HttpError
from ninja.pagination import paginate
from asgiref.sync import sync_to_async
from api.security import jwt_auth
from notification.fcm_utils import send_push_notification
from common.outbound import SuccessResponse
import os
from typing import List
from notification.models import Notification
from notification.inbound import NotificationFilterSchema
from notification.outbound import (
    NotificationResponseSchema,
    UnreadCountResponseSchema,
)


router = Router(
    tags=["Notification"],
)


@router.get(
    "",
    summary="[C] 알림 조회",
    description="사용자의 알림 목록을 조회합니다.",
    response=List[NotificationResponseSchema],
    auth=jwt_auth,
)
@paginate
async def get_notifications(request, filters: NotificationFilterSchema = Query(...)):
    user = request.auth

    @sync_to_async
    def get_notifications():
        queryset = (
            Notification.objects.select_related("user")
            .filter(user=user)
            .order_by("-created_at")
        )
        queryset = filters.filter(queryset)
        return queryset

    notifications = await get_notifications()
    return notifications


@router.get(
    "/unread-count",
    summary="읽지 않은 알림 개수 조회",
    description="사용자의 읽지 않은 알림 개수를 조회합니다.",
    response=UnreadCountResponseSchema,
    auth=jwt_auth,
)
async def get_unread_notification_count(request):
    user = request.auth

    unread_count = await Notification.objects.filter(user=user, is_read=False).acount()

    return {"unread_count": unread_count}


@router.get(
    "/read-all",
    summary="모든 알림 읽음 처리",
    description="사용자의 모든 알림을 읽음 처리합니다.",
    response=SuccessResponse,
    auth=jwt_auth,
)
async def mark_all_notifications_as_read(request):
    user = request.auth
    await Notification.objects.filter(user=user, is_read=False).aupdate(is_read=True)
    return {"message": "All notifications marked as read"}


@router.get(
    "/read/{notification_id}",
    summary="특정 알림 읽음 처리",
    description="사용자의 특정 알림을 읽음 처리합니다.",
    response=SuccessResponse,
    auth=jwt_auth,
)
async def mark_notification_as_read(request, notification_id: int):
    user = request.auth

    await Notification.objects.filter(
        user=user, id=notification_id, is_read=False
    ).aupdate(is_read=True)

    return {"message": "Notification marked as read"}


@router.get(
    "/test",
    summary="푸시 알림 테스트 API",
    description="테스트 API입니다.",
    auth=jwt_auth,
)
async def test_push_notification(request):
    user = request.auth
    if user.fcm_token is None:
        raise HttpError(400, "FCM token 을 세팅해주세요.")

    if os.environ.get("DJANGO_ENV_NAME") != "local":
        await send_push_notification(
            user.fcm_token,
            title="테스트 알림",
            body="푸시 알림 테스트입니다.",
        )
    return {"message": "Test push notification API"}
