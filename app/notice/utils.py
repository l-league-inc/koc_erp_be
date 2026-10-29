from notice.models import Notice
from ninja.errors import HttpError
from django.contrib.auth import get_user_model
from notification.models import Notification


User = get_user_model()


async def get_notice_admin_by_id(notice_id):
    try:
        notice = await Notice.objects.aget(id=notice_id)
    except Notice.DoesNotExist:
        raise HttpError(404, "해당 공지사항을 찾을 수 없습니다.")
    return notice


async def get_notice_by_id(notice_id):
    try:
        notice = await Notice.objects.aget(id=notice_id, hidden=False)
    except Notice.DoesNotExist:
        raise HttpError(404, "해당 공지사항을 찾을 수 없습니다.")
    return notice


async def make_notitication_from_notice(notice):
    users = User.objects.exclude(
        login_method=User.LoginMethodChoices.TOSS,
    ).filter(
        status=User.UserStatusChoice.ACTIVE,
    )
    notifications = []
    async for user in users:
        notifications.append(
            Notification(
                user=user,
                message=f"[{notice.get_type_display()}] {notice.title}",
                metadata={"notice_id": notice.id},
            )
        )
    if notifications:
        await Notification.objects.abulk_create(notifications)
