"""받은편지함의 새 메일을 중요도로 나눠 알림을 만듭니다.

서버 프로세스가 주기적으로 IMAP을 봅니다. 처음 본 편지함은 마지막 UID만 기록하고
이미 있던 메일은 알리지 않습니다. 그 다음부터 도착한 메일만 알립니다.
"""

from __future__ import annotations

import logging
import threading
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import close_old_connections, transaction
from ninja.errors import HttpError

from mail import daum
from mail.importance import classify_importance, normalize_levels, notice_message
from mail.models import UserMailAccount
from mail.service import _credentials, _server_for
from notification.models import Notification
from notification.utils import make_notification_sync

logger = logging.getLogger("django")

_lock = threading.Lock()
_thread: threading.Thread | None = None
_BATCH = 20


def poll_inboxes() -> int:
    account_ids = list(
        UserMailAccount.objects.filter(is_verified=True).values_list("id", flat=True)
    )
    notified = 0
    for account_id in account_ids:
        try:
            notified += poll_account(account_id)
        except Exception:
            logger.exception("mail watch failed account=%s", account_id)
    return notified


def poll_account(account_id: int) -> int:
    account = (
        UserMailAccount.objects.filter(id=account_id, is_verified=True)
        .select_related("user")
        .first()
    )
    if account is None:
        return 0
    username, password = _credentials(account)
    server = _server_for(account.provider)
    after_uid = None if account.inbox_uidvalidity is None else account.inbox_last_uid
    try:
        fetched = daum.inbox_since(
            username,
            password,
            server,
            after_uid=after_uid,
            limit=_BATCH,
        )
    except HttpError:
        logger.warning("mail watch skipped account=%s", account_id)
        return 0
    validity = int(fetched.get("uidvalidity") or 0)
    if account.inbox_uidvalidity is not None and validity != int(account.inbox_uidvalidity):
        try:
            fetched = daum.inbox_since(username, password, server, after_uid=None, limit=_BATCH)
        except HttpError:
            logger.warning("mail watch skipped account=%s", account_id)
            return 0
        return _save_cursor(
            account.id,
            account.inbox_last_uid,
            account.inbox_uidvalidity,
            int(fetched.get("highest") or 0),
            int(fetched.get("uidvalidity") or 0),
            [],
        )
    messages = list(fetched.get("messages") or [])
    if account.inbox_uidvalidity is None:
        messages = []
    return _save_cursor(
        account.id,
        account.inbox_last_uid,
        account.inbox_uidvalidity,
        int(fetched.get("highest") or 0),
        validity,
        messages,
    )


def _save_cursor(
    account_id: int,
    expected_uid: int | None,
    expected_validity: int | None,
    new_uid: int,
    new_validity: int,
    messages: list[dict],
) -> int:
    created: list[Notification] = []
    with transaction.atomic():
        locked = (
            UserMailAccount.objects.select_for_update()
            .select_related("user")
            .filter(id=account_id)
            .first()
        )
        if locked is None:
            return 0
        if locked.inbox_last_uid != expected_uid or locked.inbox_uidvalidity != expected_validity:
            return 0
        allowed = set(normalize_levels(locked.notify_importances))
        for message in messages:
            importance = classify_importance(
                subject=str(message.get("subject") or ""),
                sender=str(message.get("sender") or ""),
                snippet=str(message.get("snippet") or ""),
            )
            if importance not in allowed:
                continue
            body = notice_message(
                importance,
                str(message.get("subject") or ""),
                str(message.get("sender") or ""),
            )
            metadata = {
                "kind": "mail",
                "importance": importance,
                "uid": str(message.get("uid") or ""),
                "folder": "INBOX",
                "subject": str(message.get("subject") or ""),
                "sender": str(message.get("sender") or ""),
            }
            created.append(make_notification_sync(locked.user, body, metadata))
        locked.inbox_last_uid = new_uid
        locked.inbox_uidvalidity = new_validity
        locked.save(update_fields=["inbox_last_uid", "inbox_uidvalidity", "updated_at"])
    for notification in created:
        _publish(notification)
    return len(created)


def notification_event(notification: Notification) -> dict:
    created_at = notification.created_at
    return {
        "id": notification.id,
        "message": notification.message,
        "is_read": notification.is_read,
        "metadata": notification.metadata or {},
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def _publish(notification: Notification) -> None:
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"notification_{notification.user_id}",
            {
                "type": "new_notification",
                "notification": notification_event(notification),
                "has_unread": True,
            },
        )
    except Exception:
        logger.exception("mail notification push failed user=%s", notification.user_id)


def _loop(interval: int) -> None:
    time.sleep(5)
    while True:
        try:
            close_old_connections()
            count = poll_inboxes()
            if count:
                logger.info("mail watch notified=%s", count)
        except Exception:
            logger.exception("mail watch tick failed")
        finally:
            close_old_connections()
        time.sleep(interval)


def start_watch() -> bool:
    """설정이 켜져 있으면 받은편지함 확인 스레드를 한 번만 띄웁니다."""
    global _thread
    if not getattr(settings, "MAIL_WATCH_ENABLED", False):
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        interval = max(int(getattr(settings, "MAIL_WATCH_INTERVAL", 60)), 30)
        _thread = threading.Thread(
            target=_loop,
            args=(interval,),
            name="mail-watch",
            daemon=True,
        )
        _thread.start()
    logger.info("mail watch started interval=%ss", interval)
    return True
