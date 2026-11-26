"""Daum·Naver IMAP/SMTP 클라이언트."""

from __future__ import annotations

import email
import imaplib
import re
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from ninja.errors import HttpError

from mail.servers import MailServer

_SNIPPET_LIMIT = 200
_BODY_LIMIT = 20000
_TIMEOUT = 30


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _message_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True) or b""
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
        if plain_parts:
            return "\n".join(plain_parts)[:_BODY_LIMIT]
        if html_parts:
            stripped = re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
            return re.sub(r"\s+", " ", stripped).strip()[:_BODY_LIMIT]
        return ""
    charset = msg.get_content_charset() or "utf-8"
    payload = msg.get_payload(decode=True) or b""
    try:
        text = payload.decode(charset, errors="replace")
    except LookupError:
        text = payload.decode("utf-8", errors="replace")
    if msg.get_content_type() == "text/html":
        stripped = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", stripped).strip()[:_BODY_LIMIT]
    return text[:_BODY_LIMIT]


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return value


def _imap_login(username: str, password: str, server: MailServer) -> imaplib.IMAP4_SSL:
    try:
        client = imaplib.IMAP4_SSL(
            server.imap_host,
            server.imap_port,
            ssl_context=_ssl_context(),
            timeout=_TIMEOUT,
        )
        client.login(username, password)
        return client
    except imaplib.IMAP4.error as exc:
        raise HttpError(400, "메일 서버 로그인이 실패했습니다.") from exc
    except OSError as exc:
        raise HttpError(502, "메일 서버에 연결할 수 없습니다.") from exc


def _close_smtp(client: smtplib.SMTP | None) -> None:
    if client is None:
        return
    try:
        client.quit()
    except Exception:
        try:
            client.close()
        except Exception:
            pass


def _smtp_ssl_login(username: str, password: str, host: str, port: int) -> smtplib.SMTP_SSL:
    try:
        client = smtplib.SMTP_SSL(host, port, context=_ssl_context(), timeout=_TIMEOUT)
        client.login(username, password)
        return client
    except smtplib.SMTPAuthenticationError as exc:
        raise HttpError(400, "메일 서버 로그인이 실패했습니다.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise HttpError(502, "메일 서버에 연결할 수 없습니다.") from exc


def _smtp_login(username: str, password: str, server: MailServer) -> smtplib.SMTP:
    if server.smtp_mode == "ssl":
        return _smtp_ssl_login(username, password, server.smtp_host, server.smtp_port)
    client: smtplib.SMTP | None = None
    try:
        client = smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=_TIMEOUT)
        client.ehlo()
        if not client.has_extn("starttls"):
            raise OSError("STARTTLS unavailable")
        client.starttls(context=_ssl_context())
        client.ehlo()
        client.login(username, password)
        return client
    except smtplib.SMTPAuthenticationError as exc:
        _close_smtp(client)
        raise HttpError(400, "메일 서버 로그인이 실패했습니다.") from exc
    except HttpError:
        _close_smtp(client)
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        _close_smtp(client)
        if server.smtp_ssl_port is None:
            raise HttpError(502, "메일 서버에 연결할 수 없습니다.") from exc
        return _smtp_ssl_login(username, password, server.smtp_host, server.smtp_ssl_port)


def test_connection(username: str, password: str, server: MailServer) -> None:
    imap_client = _imap_login(username, password, server)
    try:
        imap_client.logout()
    except Exception:
        pass
    smtp_client = _smtp_login(username, password, server)
    try:
        smtp_client.quit()
    except Exception:
        pass


def _uid_tokens(data: list) -> list[bytes]:
    raw = data[0] if data else b""
    if not isinstance(raw, (bytes, bytearray)):
        return []
    return [item for item in raw.split() if item]


def _uidvalidity(client: imaplib.IMAP4_SSL) -> int:
    _status, data = client.response("UIDVALIDITY")
    if not data or data[0] in (None, b""):
        return 0
    try:
        return int(data[0])
    except (TypeError, ValueError):
        return 0


def _summaries(client: imaplib.IMAP4_SSL, uids: list[bytes], folder: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for uid in uids:
        status, fetched = client.uid(
            "fetch",
            uid,
            "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.400>)",
        )
        if status != "OK" or not fetched or fetched[0] is None:
            continue
        flags_blob = ""
        header_blob = b""
        text_blob = b""
        for part in fetched:
            if not isinstance(part, tuple) or len(part) < 2:
                if isinstance(part, (bytes, bytearray)):
                    flags_blob += part.decode("utf-8", errors="ignore")
                continue
            meta = part[0]
            if isinstance(meta, (bytes, bytearray)):
                flags_blob += meta.decode("utf-8", errors="ignore")
            payload = part[1] if isinstance(part[1], (bytes, bytearray)) else b""
            if isinstance(meta, (bytes, bytearray)) and b"HEADER" in meta.upper():
                header_blob = payload
            else:
                text_blob = payload
        msg = email.message_from_bytes(header_blob or b"")
        snippet = ""
        if text_blob:
            snippet = re.sub(r"\s+", " ", text_blob.decode("utf-8", errors="replace")).strip()
            snippet = snippet[:_SNIPPET_LIMIT]
        flags = []
        if "\\Seen" in flags_blob:
            flags.append("seen")
        if "\\Flagged" in flags_blob:
            flags.append("flagged")
        if "\\Seen" not in flags_blob:
            flags.append("unseen")
        items.append(
            {
                "uid": uid.decode("ascii") if isinstance(uid, (bytes, bytearray)) else str(uid),
                "folder": folder,
                "subject": _decode_header_value(msg.get("Subject")),
                "sender": _decode_header_value(msg.get("From")),
                "date": _parse_date(msg.get("Date")),
                "flags": flags,
                "snippet": snippet,
            }
        )
    return items


def list_messages(
    username: str,
    password: str,
    server: MailServer,
    *,
    folder: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 20), 50))
    client = _imap_login(username, password, server)
    try:
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise HttpError(400, "메일함 폴더를 열 수 없습니다.")
        criteria = "UNSEEN" if unread_only else "ALL"
        status, data = client.uid("search", None, criteria)
        if status != "OK":
            raise HttpError(502, "메일 목록을 가져오지 못했습니다.")
        uids = _uid_tokens(data)
        selected = list(reversed(uids[-limit:]))
        return _summaries(client, selected, folder)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def inbox_since(
    username: str,
    password: str,
    server: MailServer,
    *,
    after_uid: int | None,
    limit: int = 20,
) -> dict[str, Any]:
    """받은편지함에서 after_uid보다 큰 메일을 오래된 순으로 가져옵니다.

    after_uid가 None이면 알림 없이 현재 마지막 UID만 돌려줍니다.
    """
    limit = max(1, min(int(limit or 20), 20))
    client = _imap_login(username, password, server)
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise HttpError(502, "메일함 폴더를 열 수 없습니다.")
        validity = _uidvalidity(client)
        if after_uid is None:
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                raise HttpError(502, "메일 목록을 가져오지 못했습니다.")
            uids = _uid_tokens(data)
            highest = int(uids[-1]) if uids else 0
            return {"uidvalidity": validity, "highest": highest, "messages": []}
        start = int(after_uid) + 1
        status, data = client.uid("search", None, f"UID {start}:*")
        if status != "OK":
            raise HttpError(502, "메일 목록을 가져오지 못했습니다.")
        chosen = [uid for uid in _uid_tokens(data) if int(uid) >= start][:limit]
        messages = _summaries(client, chosen, "INBOX")
        highest = int(chosen[-1]) if chosen else int(after_uid)
        return {"uidvalidity": validity, "highest": highest, "messages": messages}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def get_message(
    username: str,
    password: str,
    uid: str,
    server: MailServer,
    *,
    folder: str = "INBOX",
) -> dict[str, Any]:
    if not uid or not str(uid).isdigit():
        raise HttpError(400, "메일 uid가 올바르지 않습니다.")
    client = _imap_login(username, password, server)
    try:
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise HttpError(400, "메일함 폴더를 열 수 없습니다.")
        status, fetched = client.uid("fetch", str(uid), "(FLAGS BODY.PEEK[])")
        if status != "OK" or not fetched or fetched[0] is None:
            raise HttpError(404, "메일을 찾을 수 없습니다.")
        flags_blob = ""
        raw = b""
        for part in fetched:
            if isinstance(part, tuple) and len(part) >= 2:
                meta = part[0]
                if isinstance(meta, (bytes, bytearray)):
                    flags_blob += meta.decode("utf-8", errors="ignore")
                if isinstance(part[1], (bytes, bytearray)):
                    raw = part[1]
            elif isinstance(part, (bytes, bytearray)):
                flags_blob += part.decode("utf-8", errors="ignore")
        if not raw:
            raise HttpError(404, "메일을 찾을 수 없습니다.")
        msg = email.message_from_bytes(raw)
        flags = []
        if "\\Seen" in flags_blob:
            flags.append("seen")
        if "\\Flagged" in flags_blob:
            flags.append("flagged")
        if "\\Seen" not in flags_blob:
            flags.append("unseen")
        body = _message_body(msg)
        return {
            "uid": str(uid),
            "folder": folder,
            "subject": _decode_header_value(msg.get("Subject")),
            "sender": _decode_header_value(msg.get("From")),
            "to": _decode_header_value(msg.get("To")),
            "cc": _decode_header_value(msg.get("Cc")),
            "date": _parse_date(msg.get("Date")),
            "flags": flags,
            "body": body,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def send_message(
    username: str,
    password: str,
    server: MailServer,
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> dict[str, Any]:
    recipients = [item.strip() for item in (to or []) if item and item.strip()]
    if not recipients:
        raise HttpError(400, "받는 사람이 필요합니다.")
    cc_list = [item.strip() for item in (cc or []) if item and item.strip()]
    bcc_list = [item.strip() for item in (bcc or []) if item and item.strip()]
    subject_text = (subject or "").strip()
    if not subject_text:
        raise HttpError(400, "제목이 필요합니다.")
    body_text = body or ""
    from_addr = username if "@" in username else f"{username}@{server.default_domain}"
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = ", ".join(recipients)
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    message["Subject"] = subject_text
    message.set_content(body_text)
    for filename, content, mime in attachments or []:
        maintype, subtype = mime.split("/", 1)
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    all_recipients = recipients + cc_list + bcc_list
    client = _smtp_login(username, password, server)
    try:
        client.send_message(message, from_addr=from_addr, to_addrs=all_recipients)
    except smtplib.SMTPException as exc:
        raise HttpError(502, "메일 발송에 실패했습니다.") from exc
    finally:
        try:
            client.quit()
        except Exception:
            pass
    return {
        "sender": from_addr,
        "to": recipients,
        "cc": cc_list,
        "bcc": bcc_list,
        "subject": subject_text,
    }
