from django.utils import timezone
from datetime import datetime


async def get_time_string(t: datetime) -> str:
    if t is None:
        return "없음"

    # t를 aware datetime으로 변환
    t = timezone.make_aware(t)
    now = timezone.make_aware(timezone.now())

    # 시간의 차이 계산
    time_difference = t - now
    seconds_difference = time_difference.total_seconds()
    abs_time_difference = abs(time_difference)
    hours_difference = abs_time_difference.total_seconds() / 3600
    days_difference = abs_time_difference.days

    if seconds_difference < 0:
        # 과거 시간
        if hours_difference < 1:
            minutes = int(abs_time_difference.total_seconds() / 60)
            if minutes < 1:
                return "방금 전"
            return f"{minutes}분 전"
        elif hours_difference < 24:
            hours = int(hours_difference)
            return f"{hours}시간 전"
        elif days_difference < 7:
            return f"{days_difference}일 전"
        elif days_difference < 30:
            weeks = int(days_difference / 7)
            return f"{weeks}주 전"
        elif days_difference < 365:
            months = int(days_difference / 30)
            return f"{months}개월 전"
        else:
            years = int(days_difference / 365)
            return f"{years}년 전"
    else:
        # 미래 시간
        if hours_difference < 1:
            minutes = int(abs_time_difference.total_seconds() / 60)
            if minutes < 1:
                return "곧"
            return f"{minutes}분 후"
        elif hours_difference < 24:
            hours = int(hours_difference)
            return f"{hours}시간 후"
        elif days_difference < 7:
            return f"{days_difference}일 후"
        elif days_difference < 30:
            weeks = int(days_difference / 7)
            return f"{weeks}주 후"
        elif days_difference < 365:
            months = int(days_difference / 30)
            return f"{months}개월 후"
        else:
            years = int(days_difference / 365)
            return f"{years}년 후"
