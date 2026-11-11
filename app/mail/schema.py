from datetime import datetime
from typing import Optional

from ninja import Schema


class MailAccountUpsertSchema(Schema):
    username: str
    app_password: str


class MailAccountResponseSchema(Schema):
    configured: bool
    provider: str
    username: str
    username_masked: str
    is_verified: bool
    last_verified_at: Optional[datetime] = None
    last_error: str = ""


class MailMessageListItemSchema(Schema):
    uid: str
    folder: str
    subject: str
    sender: str
    date: Optional[str] = None
    flags: list[str]
    snippet: str


class MailMessageDetailSchema(Schema):
    uid: str
    folder: str
    subject: str
    sender: str
    to: str = ""
    cc: str = ""
    date: Optional[str] = None
    flags: list[str]
    body: str


class MailSendSchema(Schema):
    to: list[str]
    subject: str
    body: str
    cc: Optional[list[str]] = None
    bcc: Optional[list[str]] = None


class MailSendResponseSchema(Schema):
    sender: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
