import re
from urllib.parse import urlparse

# 자동화 봇이 자주 스캔하는 민감 경로
SCANNER_PATH_PATTERN = re.compile(
    r"^/("
    r"\.env(\..*)?"
    r"|\.git(/.*)?"
    r"|wp-admin(/.*)?"
    r"|phpmyadmin(/.*)?"
    r"|\.aws(/.*)?"
    r"|config\.json"
    r"|\.htaccess"
    r"|web\.config"
    r")$",
    re.IGNORECASE,
)


def extract_request_path(url: str) -> str:
    if not url:
        return ""
    path = urlparse(url).path if "://" in url else url.split("?")[0]
    return path.rstrip("/") or "/"


def is_scanner_request(url: str) -> bool:
    path = extract_request_path(url)
    if path == "/":
        return False
    return bool(SCANNER_PATH_PATTERN.match(path))


def before_send(event, hint):
    request = event.get("request") or {}
    url = request.get("url") or event.get("transaction") or ""
    if is_scanner_request(url):
        return None
    return event


def before_send_transaction(event, hint):
    request = event.get("request") or {}
    url = request.get("url") or event.get("transaction") or ""
    if is_scanner_request(url):
        return None
    return event
