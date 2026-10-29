from notification.models import Notification
from notification.fcm_utils import send_push_notification


def make_notification_sync(user, message, metadata=None):
    Notification.objects.create(
        user=user,
        message=message,
        metadata=metadata or {},
        is_read=False,
    )
    if user and user.push_notification and user.fcm_token:
        try:
            from firebase_admin import messaging

            messaging.send(
                messaging.Message(
                    notification=messaging.Notification(
                        title="KOC ERP",
                        body=message,
                    ),
                    token=user.fcm_token,
                )
            )
        except Exception:
            pass


async def make_notification(user, message, metadata=None):
    await Notification.objects.acreate(
        user=user,
        message=message,
        metadata=metadata or {},
        is_read=False,
    )
    if user and user.push_notification and user.fcm_token:
        await send_push_notification(
            token=user.fcm_token, title="KOC ERP", body=message
        )
