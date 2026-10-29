from typing import Any

_EXACT_KEYS = {"password", "access", "refresh", "token", "secret"}
_KEY_PARTS = ("password", "secret", "token", "refresh")


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in _EXACT_KEYS:
        return True
    if any(part in lowered for part in _KEY_PARTS):
        return True
    if (
        lowered == "access"
        or lowered.endswith("_access")
        or lowered.startswith("access_")
        or "access_token" in lowered
    ):
        return True
    return False


def redact(value: Any) -> Any:
    """응답에서 비밀번호, 토큰, 시크릿 키를 제거합니다."""
    if isinstance(value, dict):
        return {
            str(key): redact(item)
            for key, item in value.items()
            if not is_sensitive_key(str(key))
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def omit_user_integer_ids(value: Any) -> Any:
    """email이 있는 사용자 객체에서 정수 id만 제거합니다. email과 name은 남깁니다."""
    if isinstance(value, list):
        return [omit_user_integer_ids(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {str(key): omit_user_integer_ids(item) for key, item in value.items()}
    if "email" in cleaned and isinstance(cleaned.get("id"), int):
        cleaned.pop("id")
    return cleaned
