from user.models import User, Jwt
from asgiref.sync import sync_to_async
from user import utils
from django.conf import settings
import logging


logger = logging.getLogger("django")


async def find_user_social_login(
    email, login_method, social_username, social_email, phone_number, gender
):

    created = False

    @sync_to_async
    def create_social_user():
        user = User.objects.create_user(
            email=email,
            login_method=login_method,
            social_username=social_username,
            social_email=social_email,
            phone_number=phone_number,
            status=User.UserStatusChoice.ACTIVE,
            type=User.UserTypeChoices.MEMBER,
        )
        user.set_unusable_password()
        user.save()
        logger.info(
            f"Created new social user: id={user.id}, email={email}, social_email={social_email}"
        )
        return user

    try:
        user = await User.objects.aget(
            login_method=login_method,
            social_email=social_email,
            status=User.UserStatusChoice.ACTIVE,  # 활성 유저만 검색
        )
        logger.info(
            f"Found existing active user: id={user.id}, social_email={social_email}"
        )
    except User.DoesNotExist:
        logger.info(
            f"No active user found with social_email={social_email}, creating new user"
        )
        user = await create_social_user()
        created = True

    if not created:
        if user.social_email != social_email:
            user.social_email = social_email
            await user.asave()
        if phone_number is not None and user.phone_number != phone_number:
            user.phone_number = phone_number
            await user.asave()

    access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    await Jwt.objects.acreate(
        user_id=user.id,
        access=access,
        refresh=refresh,
    )

    return user, created, access, refresh, access_exp, refresh_exp
