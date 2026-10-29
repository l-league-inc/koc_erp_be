from datetime import datetime, timedelta

from ninja.errors import HttpError

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _expand(expr: str, low: int, high: int, *, dow: bool = False) -> set[int]:
    values: set[int] = set()
    for part in expr.split(","):
        piece = part.strip()
        if not piece:
            raise ValueError
        step = 1
        if "/" in piece:
            base, step_text = piece.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError
            step = int(step_text)
        else:
            base = piece
        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            if not left.isdigit() or not right.isdigit():
                raise ValueError
            start, end = int(left), int(right)
        else:
            if not base.isdigit():
                raise ValueError
            start = end = int(base)
        if start > end or start < low or end > high:
            raise ValueError
        values.update(range(start, end + 1, step))
    if dow:
        if 7 in values:
            values.add(0)
        if 0 in values:
            values.add(7)
    return values


def parse_cron(expression: str) -> tuple[str, str, str, str, str]:
    parts = (expression or "").split()
    if len(parts) != 5:
        raise HttpError(400, "일정은 분 시 일 월 요일 다섯 칸입니다.")
    try:
        for part, (low, high), is_dow in zip(parts, _RANGES, (False, False, False, False, True)):
            _expand(part, low, high, dow=is_dow)
    except ValueError:
        raise HttpError(400, "일정 형식이 올바르지 않습니다.") from None
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def _matches(moment: datetime, fields: tuple[str, str, str, str, str]) -> bool:
    minute, hour, day, month, weekday = fields
    if moment.minute not in _expand(minute, 0, 59):
        return False
    if moment.hour not in _expand(hour, 0, 23):
        return False
    if moment.month not in _expand(month, 1, 12):
        return False
    day_match = moment.day in _expand(day, 1, 31)
    cron_weekday = (moment.weekday() + 1) % 7
    weekday_match = cron_weekday in _expand(weekday, 0, 7, dow=True)
    if day == "*" and weekday == "*":
        return True
    if day == "*":
        return weekday_match
    if weekday == "*":
        return day_match
    return day_match or weekday_match


def next_run_at(expression: str, after: datetime) -> datetime:
    fields = parse_cron(expression)
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = cursor + timedelta(days=366)
    while cursor <= limit:
        if _matches(cursor, fields):
            return cursor
        cursor += timedelta(minutes=1)
    raise HttpError(400, "다음 실행 시각을 계산할 수 없습니다.")
