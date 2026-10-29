import random

from django.contrib.auth import get_user_model
from django.db.models import Q

MAX_NICKNAME_LENGTH = 30
MAX_GENERATION_ATTEMPTS = 50

NICKNAME_ADJECTIVES: tuple[str, ...] = (
    "맑은",
    "조용한",
    "빠른",
    "깊은",
    "밝은",
    "새로운",
    "단단한",
    "가벼운",
    "푸른",
    "따뜻한",
)

NICKNAME_NOUNS: tuple[str, ...] = (
    "하늘",
    "바다",
    "숲",
    "별",
    "구름",
    "바람",
    "노을",
    "달",
    "강",
    "섬",
)


def build_nickname_candidate() -> str:
    """형용사 + 명사 + 명사 조합으로 닉네임 후보를 생성합니다."""
    adjective = random.choice(NICKNAME_ADJECTIVES)
    noun1, noun2 = random.sample(NICKNAME_NOUNS, 2)
    nickname = f"{adjective}{noun1}{noun2}"

    if len(nickname) > MAX_NICKNAME_LENGTH:
        raise ValueError(
            f"생성된 닉네임이 최대 길이({MAX_NICKNAME_LENGTH})를 초과했습니다: {nickname}"
        )

    return nickname


def is_nickname_taken(nickname: str, exclude_user_id: int | None = None) -> bool:
    user_model = get_user_model()
    queryset = user_model.objects.filter(nickname=nickname)
    if exclude_user_id is not None:
        queryset = queryset.exclude(id=exclude_user_id)
    return queryset.exists()


def generate_unique_nickname(exclude_user_id: int | None = None) -> str:
    """DB에서 중복되지 않는 닉네임을 생성합니다."""
    for _ in range(MAX_GENERATION_ATTEMPTS):
        nickname = build_nickname_candidate()
        if not is_nickname_taken(nickname, exclude_user_id=exclude_user_id):
            return nickname

    # 조합이 모두 소진된 경우 숫자 접미사로 유일성 확보
    for _ in range(MAX_GENERATION_ATTEMPTS):
        base_nickname = build_nickname_candidate()
        suffix = str(random.randint(100, 9999))
        max_base_length = MAX_NICKNAME_LENGTH - len(suffix)
        nickname = f"{base_nickname[:max_base_length]}{suffix}"
        if not is_nickname_taken(nickname, exclude_user_id=exclude_user_id):
            return nickname

    raise RuntimeError("고유한 닉네임을 생성하지 못했습니다.")


def is_missing_nickname(nickname: str | None) -> bool:
    return not nickname or not nickname.strip()


def user_has_nickname(user) -> bool:
    return not is_missing_nickname(user.nickname)


def get_users_without_nickname():
    user_model = get_user_model()
    return user_model.objects.filter(Q(nickname__isnull=True) | Q(nickname=""))
