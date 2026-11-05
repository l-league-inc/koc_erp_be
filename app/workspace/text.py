"""블록 JSON에서 화면에 보이는 글만 모읍니다."""

from typing import Any


def extract_plain_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    parts: list[str] = []

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if text:
            parts.append(text)

    add(content.get("text"))
    add(content.get("formula"))
    add(content.get("file_name"))
    add(content.get("title"))
    add(content.get("description"))
    rich_text = content.get("rich_text")
    if isinstance(rich_text, list):
        for item in rich_text:
            if not isinstance(item, dict):
                continue
            add(item.get("text"))
            add(item.get("formula"))
    return " ".join(parts)
