import uuid
from datetime import timedelta

from django.utils import timezone

from user.kakao_utils import find_user_social_login
from user.models import User


class SocialAccountConflict(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def resolve_kakao_user(
    kakao_user_id: str,
    social_email: str | None,
    phone_number: str | None,
    gender: str | None,
) -> User:
    """앱 카카오 로그인과 같은 계정 매칭입니다. JWT는 발급하지 않습니다."""
    await _reject_email_account_collision(social_email, phone_number)
    existing = await _login_method_user(str(kakao_user_id), User.LoginMethodChoices.KAKAO)
    if existing is not None:
        return existing

    try:
        withdrawn = await User.objects.aget(
            social_user_id=str(kakao_user_id),
            login_method=User.LoginMethodChoices.KAKAO,
            status=User.UserStatusChoice.WITHDRAW,
            withdraw_at__isnull=False,
        )
    except User.DoesNotExist:
        withdrawn = None

    if withdrawn is not None and withdrawn.withdraw_at >= timezone.now() - timedelta(days=7):
        withdrawn.social_user_id = str(kakao_user_id)
        withdrawn.last_login = timezone.now()
        await withdrawn.asave()
        return withdrawn

    if withdrawn is not None:
        withdrawn.social_user_id = None
        withdrawn.social_email = None
        await withdrawn.asave()

    unique_username = f"kakao-{social_email}-{uuid.uuid4()}"
    user, _created, *_rest = await find_user_social_login(
        email=unique_username,
        login_method=User.LoginMethodChoices.KAKAO,
        social_username=unique_username,
        social_email=social_email,
        phone_number=phone_number,
        gender=gender,
    )
    user.last_login = timezone.now()
    user.social_user_id = str(kakao_user_id)
    await user.asave()
    return user


async def resolve_apple_user(
    apple_user_id: str,
    email: str | None,
    user_name: str | None,
) -> User:
    """앱 애플 로그인과 같은 계정 매칭입니다. JWT는 발급하지 않습니다."""
    if email:
        email_taken = await User.objects.filter(
            email=email,
            login_method=User.LoginMethodChoices.EMAIL,
        ).aexists()
        if email_taken:
            raise SocialAccountConflict(
                f"{email}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요."
            )

    existing = await _login_method_user(str(apple_user_id), User.LoginMethodChoices.APPLE)
    if existing is not None:
        if email:
            existing.social_email = email
        if user_name and not existing.name:
            existing.name = user_name
        existing.last_login = timezone.now()
        await existing.asave()
        return existing

    try:
        withdrawn = await User.objects.aget(
            social_user_id=str(apple_user_id),
            login_method=User.LoginMethodChoices.APPLE,
            status=User.UserStatusChoice.WITHDRAW,
            withdraw_at__isnull=False,
        )
    except User.DoesNotExist:
        withdrawn = None

    if withdrawn is not None and withdrawn.withdraw_at >= timezone.now() - timedelta(days=7):
        withdrawn.last_login = timezone.now()
        if email:
            withdrawn.social_email = email
        if user_name and not withdrawn.name:
            withdrawn.name = user_name
        await withdrawn.asave()
        return withdrawn

    if withdrawn is not None:
        withdrawn.social_user_id = None
        withdrawn.social_email = None
        await withdrawn.asave()

    return await _create_apple_user(apple_user_id, email, user_name)


async def _reject_email_account_collision(
    social_email: str | None, phone_number: str | None
) -> None:
    if social_email:
        email_taken = (
            await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
            .filter(email=social_email, login_method=User.LoginMethodChoices.EMAIL)
            .aexists()
        )
        if email_taken:
            raise SocialAccountConflict(
                f"{social_email}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요."
            )
    if phone_number:
        phone_taken = await User.objects.filter(
            phone_number=phone_number,
            login_method=User.LoginMethodChoices.EMAIL,
        ).aexists()
        if phone_taken:
            raise SocialAccountConflict(
                f"{phone_number}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요."
            )


async def _login_method_user(social_user_id: str, login_method: str) -> User | None:
    user = (
        await User.objects.filter(
            social_user_id=social_user_id,
            login_method=login_method,
        )
        .exclude(status=User.UserStatusChoice.WITHDRAW)
        .afirst()
    )
    if user is None:
        return None
    if user.status == User.UserStatusChoice.SUSPENDED:
        raise SocialAccountConflict("정지되었거나 탈퇴한 계정입니다.")
    user.last_login = timezone.now()
    await user.asave(update_fields=["last_login"])
    return user


async def _create_apple_user(
    apple_user_id: str, email: str | None, user_name: str | None
) -> User:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def create() -> User:
        unique_username = f"apple-{email or apple_user_id}-{uuid.uuid4()}"
        user = User.objects.create_user(
            email=unique_username,
            login_method=User.LoginMethodChoices.APPLE,
            social_username=unique_username,
            social_email=email,
            social_user_id=str(apple_user_id),
            name=user_name,
            status=User.UserStatusChoice.ACTIVE,
            type=User.UserTypeChoices.MEMBER,
            last_login=timezone.now(),
        )
        user.set_unusable_password()
        user.save()
        return user

    return await create()
