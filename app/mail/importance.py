"""받은 메일의 업무 중요도.

긴급은 오늘 처리해야 하는 장애, 마감, 클레임, 미수입니다.
낮음은 뉴스레터와 자동 발송입니다.
그 외 업무 메일은 보통입니다. 긴급 문구가 있으면 낮음보다 긴급이 우선입니다.
"""

from __future__ import annotations

LEVELS = ("urgent", "normal", "low")
LABELS = {"urgent": "긴급", "normal": "보통", "low": "낮음"}

_URGENT = (
    "긴급",
    "즉시 확인",
    "즉시 처리",
    "당장",
    "오늘까지",
    "오늘 마감",
    "금일 마감",
    "장애",
    "서버 다운",
    "서비스 중단",
    "업무 중단",
    "클레임",
    "항의",
    "계약 해지",
    "소송",
    "내용증명",
    "미수",
    "연체",
    "독촉",
    "결제 실패",
    "지급 지연",
    "asap",
    "urgent",
)
_LOW = (
    "noreply",
    "no-reply",
    "newsletter",
    "unsubscribe",
    "mailer-daemon",
    "뉴스레터",
    "수신거부",
    "광고메일",
    "프로모션",
)


def normalize_levels(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return list(LEVELS)
    chosen: list[str] = []
    for item in raw:
        if item in LEVELS and item not in chosen:
            chosen.append(str(item))
    return chosen or list(LEVELS)


def classify_importance(*, subject: str, sender: str, snippet: str) -> str:
    text = f"{subject}\n{snippet}".lower()
    if any(token in text for token in _URGENT):
        return "urgent"
    haystack = f"{sender}\n{text}".lower()
    if any(token in haystack for token in _LOW):
        return "low"
    return "normal"


def notice_message(importance: str, subject: str, sender: str) -> str:
    label = LABELS.get(importance, LABELS["normal"])
    title = (subject or "").strip() or "(제목 없음)"
    who = (sender or "").strip()
    text = f"[{label}] {title}"
    if who:
        text = f"{text} · {who}"
    return text[:200]
