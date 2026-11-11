"""메일 계정·조회·발송 비즈니스 로직."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from mail import crypto, daum
from mail.models import UserMailAccount


def _mask_username(username: str) -> str:
    text = (username or "").strip()
    if not text:
        return ""
    if "@" in text:
        local, _, domain = text.partition("@")
        if not local:
            return f"***@{domain}"
        if len(local) <= 2:
            return f"{local[0]}***@{domain}"
        return f"{local[:2]}***@{domain}"
    if len(text) <= 2:
        return f"{text[0]}***"
    return f"{text[:2]}***"


def serialize_account(account: UserMailAccount | None) -> dict[str, Any]:
    if account is None:
        return {
            "configured": False,
            "provider": UserMailAccount.Provider.DAUM,
            "username": "",
            "username_masked": "",
            "is_verified": False,
            "last_verified_at": None,
            "last_error": "",
        }
    return {
        "configured": True,
        "provider": account.provider,
        "username": account.username,
        "username_masked": _mask_username(account.username),
        "is_verified": account.is_verified,
        "last_verified_at": account.last_verified_at,
        "last_error": account.last_error or "",
    }


def get_account(user) -> dict[str, Any]:
    account = UserMailAccount.objects.filter(user=user).first()
    return serialize_account(account)


def _load_account(user) -> UserMailAccount:
    account = UserMailAccount.objects.filter(user=user).first()
    if account is None:
        raise HttpError(400, "메일 계정이 연결되어 있지 않습니다. 설정에서 Daum 메일 아이디와 앱 비밀번호를 등록하세요.")
    return account


def _credentials(account: UserMailAccount) -> tuple[str, str]:
    return account.username, crypto.decrypt_secret(account.password_encrypted)


@transaction.atomic
def upsert_account(user, username: str, app_password: str) -> dict[str, Any]:
    name = (username or "").strip()
    password = (app_password or "").strip()
    if not name:
        raise HttpError(400, "메일 아이디가 필요합니다.")
    if not password:
        raise HttpError(400, "앱 비밀번호가 필요합니다.")
    try:
        daum.test_connection(name, password)
    except HttpError as exc:
        account = UserMailAccount.objects.filter(user=user).first()
        if account is not None:
            account.last_error = str(exc.message)
            account.is_verified = False
            account.save(update_fields=["last_error", "is_verified", "updated_at"])
        raise
    encrypted = crypto.encrypt_secret(password)
    account = UserMailAccount.objects.filter(user=user).first()
    if account is None:
        deleted = UserMailAccount.all_objects.filter(user=user, deleted_at__isnull=False).first()
        if deleted is not None:
            deleted.restore()
            account = deleted
        else:
            account = UserMailAccount(user=user)
    account.provider = UserMailAccount.Provider.DAUM
    account.username = name
    account.password_encrypted = encrypted
    account.is_verified = True
    account.last_verified_at = timezone.now()
    account.last_error = ""
    account.save()
    return serialize_account(account)


@transaction.atomic
def delete_account(user) -> None:
    account = UserMailAccount.objects.filter(user=user).first()
    if account is None:
        raise HttpError(404, "메일 계정을 찾을 수 없습니다.")
    account.delete()


def list_messages(
    user,
    *,
    folder: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    account = _load_account(user)
    username, password = _credentials(account)
    folder_name = (folder or "INBOX").strip() or "INBOX"
    try:
        return daum.list_messages(
            username,
            password,
            folder=folder_name,
            limit=limit,
            unread_only=unread_only,
        )
    except HttpError as exc:
        account.last_error = str(exc.message)
        account.save(update_fields=["last_error", "updated_at"])
        raise


def get_message(user, uid: str, *, folder: str = "INBOX") -> dict[str, Any]:
    account = _load_account(user)
    username, password = _credentials(account)
    folder_name = (folder or "INBOX").strip() or "INBOX"
    try:
        return daum.get_message(username, password, uid, folder=folder_name)
    except HttpError as exc:
        account.last_error = str(exc.message)
        account.save(update_fields=["last_error", "updated_at"])
        raise


def send_message(
    user,
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, Any]:
    account = _load_account(user)
    username, password = _credentials(account)
    try:
        return daum.send_message(
            username,
            password,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )
    except HttpError as exc:
        account.last_error = str(exc.message)
        account.save(update_fields=["last_error", "updated_at"])
        raise
