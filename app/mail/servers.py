"""Daum·Naver 메일 서버 주소입니다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MailServer:
    provider: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    smtp_mode: str
    smtp_ssl_port: int | None
    default_domain: str


DAUM = MailServer(
    provider="daum",
    imap_host="imap.daum.net",
    imap_port=993,
    smtp_host="smtp.daum.net",
    smtp_port=465,
    smtp_mode="ssl",
    smtp_ssl_port=None,
    default_domain="daum.net",
)
NAVER = MailServer(
    provider="naver",
    imap_host="imap.naver.com",
    imap_port=993,
    smtp_host="smtp.naver.com",
    smtp_port=587,
    smtp_mode="starttls",
    smtp_ssl_port=465,
    default_domain="naver.com",
)

_BY_PROVIDER = {DAUM.provider: DAUM, NAVER.provider: NAVER}


def get_server(provider: str) -> MailServer | None:
    return _BY_PROVIDER.get((provider or "").strip().lower())
