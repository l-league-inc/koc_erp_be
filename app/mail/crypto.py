"""메일 앱 비밀번호 AES-256-GCM 암·복호화."""

from __future__ import annotations

import base64
import hashlib
import os

from Crypto.Cipher import AES
from django.conf import settings
from ninja.errors import HttpError

_IV_LENGTH = 12
_TAG_LENGTH = 16
_AAD = b"koc-mail-credentials"


def _key_bytes() -> bytes:
    raw = (getattr(settings, "MAIL_CREDENTIALS_KEY", None) or "").strip()
    if raw:
        try:
            key = base64.b64decode(raw)
        except Exception as exc:
            raise HttpError(500, "메일 자격증명 키가 올바르지 않습니다.") from exc
        if len(key) != 32:
            raise HttpError(500, "메일 자격증명 키 길이가 올바르지 않습니다.")
        return key
    secret = getattr(settings, "SECRET_KEY", "") or ""
    if not secret:
        raise HttpError(500, "메일 자격증명 키가 설정되지 않았습니다.")
    return hashlib.sha256(f"mail-credentials:{secret}".encode("utf-8")).digest()


def encrypt_secret(plain: str) -> str:
    text = (plain or "").encode("utf-8")
    iv = os.urandom(_IV_LENGTH)
    cipher = AES.new(_key_bytes(), AES.MODE_GCM, nonce=iv)
    cipher.update(_AAD)
    ciphertext, tag = cipher.encrypt_and_digest(text)
    return base64.b64encode(iv + ciphertext + tag).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        decoded = base64.b64decode(token)
        iv = decoded[:_IV_LENGTH]
        tag = decoded[-_TAG_LENGTH:]
        ciphertext = decoded[_IV_LENGTH:-_TAG_LENGTH]
        cipher = AES.new(_key_bytes(), AES.MODE_GCM, nonce=iv)
        cipher.update(_AAD)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
    except HttpError:
        raise
    except Exception as exc:
        raise HttpError(400, "저장된 메일 비밀번호를 읽을 수 없습니다.") from exc
